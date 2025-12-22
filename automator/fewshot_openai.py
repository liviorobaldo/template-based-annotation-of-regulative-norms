"""Few-shot legal annotation helper.

This script sends the full legislative JSON payload to an OpenAI chat model using
an external prompt template stored in ``prompt.txt`` and includes examples from
``examples.json`` for few-shot learning.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional, Sequence, Tuple

import openai

try:
    from openai import OpenAI  # type: ignore
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore

try:
    from dotenv import load_dotenv  # type: ignore
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore

LOGGER = logging.getLogger("fewshot_openai")
if not LOGGER.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

SYSTEM_PROMPT = (
    "You are an expert legal annotator who extracts and formats obligations, "
    "prohibitions, and permissions from legislative text. Respond with precise "
    "and well-structured JSON only."
)

DEFAULT_PROMPT_PATH = Path(__file__).with_name("prompt.txt")
DEFAULT_EXAMPLES_PATH = Path(__file__).with_name("examples.json")

_CLIENT: Optional[Any] = None
_USING_LEGACY_API = False

_DEFAULT_SCHEMA_HINTS = ("json", "JSON")


def read_prompt_template(prompt_path: Path) -> str:
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found at {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


def load_examples(examples_path: Path) -> list[dict]:
    """Load examples from JSON file."""
    if not examples_path.exists():
        raise FileNotFoundError(f"Examples file not found at {examples_path}")
    with examples_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    elif isinstance(data, dict) and "examples" in data:
        return data["examples"]
    else:
        raise ValueError(f"Examples file must contain a list or dict with 'examples' key")


def load_document_payload(json_path: Path) -> str:
    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return json.dumps(data, ensure_ascii=False, indent=2)


def build_user_prompt(
    template: str,
    *,
    document_json: str,
    source_path: Path,
    examples: list[dict],
    num_examples: int = 3
) -> str:
    """Build user prompt with examples."""
    # Format examples
    examples_text = "\n\nHere are some examples of correctly formatted annotations:\n\n"
    for i, example in enumerate(examples[:num_examples], 1):
        examples_text += f"Example {i}:\n"
        examples_text += json.dumps(example, ensure_ascii=False, indent=2)
        examples_text += "\n\n"
    
    # Replace placeholders
    prompt = template.replace("{{SOURCE_PATH}}", str(source_path))
    
    # Insert examples after the guidelines but before the document JSON
    # The template should have "{{DOCUMENT_JSON}}" at the end
    prompt = prompt.replace("{{DOCUMENT_JSON}}", examples_text + "Legislative JSON payload (use as-is without reformatting):\n" + document_json)
    
    return prompt


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        without_prefix = stripped[3:]
        for hint in _DEFAULT_SCHEMA_HINTS:
            if without_prefix.startswith(hint):
                without_prefix = without_prefix[len(hint):]
                break
        stripped = without_prefix.lstrip()
    if stripped.endswith("```"):
        stripped = stripped[:-3].rstrip()
    return stripped


def _normalise_json_text(text: str) -> str:
    cleaned = text.replace("```json", "").replace("```", "")
    cleaned = _strip_code_fence(cleaned)
    while cleaned and cleaned[0] in {'"', "'"} and cleaned[-1] == cleaned[0]:
        cleaned = cleaned[1:-1].strip()
    return cleaned


def ensure_openai_client(api_key: Optional[str]) -> Any:
    global _CLIENT, _USING_LEGACY_API
    if _CLIENT is not None:
        return _CLIENT

    if load_dotenv is not None:
        load_dotenv()

    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        raise ValueError("OpenAI API key is required via --api-key or OPENAI_API_KEY env var.")

    os.environ["OPENAI_API_KEY"] = key

    if OpenAI is not None:
        _CLIENT = OpenAI(api_key=key)
        _USING_LEGACY_API = False
        try:  # Maintain compatibility if other modules still rely on openai.api_key
            openai.api_key = key
        except AttributeError:  # pragma: no cover
            pass
    else:
        openai.api_key = key
        _CLIENT = openai
        _USING_LEGACY_API = True

    return _CLIENT


def call_model(*, model: str, user_prompt: str, temperature: float, max_tokens: int) -> str:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    client = ensure_openai_client(None)

    if _USING_LEGACY_API:
        response = client.ChatCompletion.create(  # type: ignore[attr-defined]
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = response["choices"][0]["message"]["content"]
    else:
        response = client.chat.completions.create(  # type: ignore[attr-defined]
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = response.choices[0].message.content

    return content.strip()


def annotate_json(
    *,
    json_path: Path,
    model: str,
    prompt_path: Path = DEFAULT_PROMPT_PATH,
    examples_path: Path = DEFAULT_EXAMPLES_PATH,
    api_key: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 4000,
    num_examples: int = 3,
) -> Tuple[str, Optional[Any]]:
    ensure_openai_client(api_key)
    template = read_prompt_template(prompt_path)
    examples = load_examples(examples_path)
    document_json = load_document_payload(json_path)
    user_prompt = build_user_prompt(
        template,
        document_json=document_json,
        source_path=json_path,
        examples=examples,
        num_examples=num_examples
    )
    LOGGER.info("Submitting %s to model %s (few-shot with %d examples)", json_path.name, model, num_examples)
    raw_response = call_model(model=model, user_prompt=user_prompt, temperature=temperature, max_tokens=max_tokens)
    parsed = None
    normalised = _normalise_json_text(raw_response)
    if normalised:
        try:
            parsed = json.loads(normalised)
        except json.JSONDecodeError:
            LOGGER.warning("Model response was not valid JSON after normalisation. Returning raw text only.")
        else:
            raw_response = normalised
    return raw_response, parsed


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, data: Any) -> None:
    _ensure_parent(path)
    with path.open("w", encoding="utf-8") as output_file:
        json.dump(data, output_file, ensure_ascii=False, indent=2)
    LOGGER.info("Saved parsed JSON output to %s", path)


def _write_text(path: Path, text: str) -> None:
    _ensure_parent(path)
    with path.open("w", encoding="utf-8") as output_file:
        output_file.write(text)
    LOGGER.info("Saved raw model output to %s", path)


def _derive_raw_path(base_path: Path) -> Path:
    try:
        return base_path.with_suffix(".raw.txt")
    except ValueError:
        return base_path.with_name(base_path.name + ".raw.txt")


def run_cli(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Few-shot annotation over legislative JSON payloads")
    parser.add_argument("json_path", type=Path, help="Path to the legislative JSON file")
    parser.add_argument("--model", default="gpt-4o", help="Chat model to call")
    parser.add_argument("--prompt-path", type=Path, default=DEFAULT_PROMPT_PATH, help="Path to the prompt template")
    parser.add_argument("--examples-path", type=Path, default=DEFAULT_EXAMPLES_PATH, help="Path to the examples JSON file")
    parser.add_argument("--api-key", help="OpenAI API key (default: OPENAI_API_KEY env var)")
    parser.add_argument("--temperature", type=float, default=0.2, help="Sampling temperature")
    parser.add_argument("--max-tokens", type=int, default=4000, help="Maximum tokens in the response")
    parser.add_argument("--num-examples", type=int, default=3, help="Number of examples to include in the prompt")
    parser.add_argument("--output", type=Path, help="Optional path to write the parsed JSON output")
    parser.add_argument("--raw-output", type=Path, help="Always write the raw model response to this path")
    parser.add_argument("--print-raw", action="store_true", help="Print the raw model response to stdout")

    args = parser.parse_args(args=argv)
    raw_response, parsed = annotate_json(
        json_path=args.json_path,
        model=args.model,
        prompt_path=args.prompt_path,
        examples_path=args.examples_path,
        api_key=args.api_key,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        num_examples=args.num_examples,
    )

    raw_already_saved = False

    if parsed is not None and args.output is not None:
        _write_json(args.output, parsed)
    elif parsed is None:
        fallback_target = args.raw_output
        if fallback_target is None:
            if args.output is not None:
                fallback_target = _derive_raw_path(args.output)
            else:
                fallback_target = _derive_raw_path(args.json_path)
        _write_text(fallback_target, raw_response)
        raw_already_saved = fallback_target == args.raw_output

    if args.raw_output is not None and not raw_already_saved:
        _write_text(args.raw_output, raw_response)

    if args.print_raw or (args.output is None and args.raw_output is None):
        print(raw_response if parsed is None else json.dumps(parsed, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run_cli()

