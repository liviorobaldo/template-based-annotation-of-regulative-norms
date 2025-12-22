"""
Few-shot automation for legal annotation.
Uses example annotations from the unified dataset to guide the model.
"""
import argparse
import csv
import json
import logging
import os
from pathlib import Path
from typing import List, Optional, Dict, Any

from openai import OpenAI
from dotenv import load_dotenv

LOGGER = logging.getLogger("fewshot_automation")
if not LOGGER.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

SYSTEM_PROMPT = (
    "You are an expert legal annotator who extracts and formats obligations, "
    "prohibitions, and permissions from legislative text. You will be provided "
    "with example annotations to guide your work. Respond with precise and "
    "well-structured JSON only."
)

DEFAULT_PROMPT_PATH = Path(__file__).with_name("prompt.txt")


def read_prompt_template(prompt_path: Path) -> str:
    """Read the prompt template file."""
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found at {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


def load_document_payload(json_path: Path) -> str:
    """Load and format document JSON payload."""
    with json_path.open("r", encoding="utf-8") as json_file:
        data = json.load(json_file)
    return json.dumps(data, ensure_ascii=False, indent=2)


def select_example_annotations(
    unified_csv: str,
    num_examples: int = 3,
    exclude_legislation_id: Optional[str] = None
) -> List[Dict]:
    """Select example annotations from the unified dataset."""
    examples = []
    
    try:
        with open(unified_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            
            # Filter out the current legislation if specified
            if exclude_legislation_id:
                rows = [r for r in rows if r['legislation_id'] != exclude_legislation_id]
            
            # Select first N examples
            for row in rows[:num_examples]:
                try:
                    annotations = json.loads(row['annotations'])
                    if annotations and len(annotations) > 0:
                        # Use the first annotation from each legislation as example
                        examples.append(annotations[0])
                except json.JSONDecodeError:
                    continue
                
                if len(examples) >= num_examples:
                    break
    except Exception as e:
        LOGGER.warning(f"Error loading examples: {e}")
    
    return examples


def format_examples_for_prompt(examples: List[Dict]) -> str:
    """Format example annotations as a string for the prompt."""
    if not examples:
        return ""
    
    examples_text = "Here are example annotations to guide you:\n\n"
    for i, example in enumerate(examples, 1):
        examples_text += f"Example {i}:\n"
        examples_text += json.dumps(example, ensure_ascii=False, indent=2)
        examples_text += "\n\n"
    
    return examples_text


def build_fewshot_prompt(
    template: str,
    document_json: str,
    source_path: Path,
    examples: List[Dict]
) -> str:
    """Build the few-shot prompt with examples."""
    prompt = template.replace("{{DOCUMENT_JSON}}", document_json)
    prompt = prompt.replace("{{SOURCE_PATH}}", str(source_path))
    
    # Insert examples after the guidelines
    examples_text = format_examples_for_prompt(examples)
    
    # Insert examples before the document JSON
    if "{{DOCUMENT_JSON}}" in template:
        # Already replaced, insert before document section
        prompt = prompt.replace(
            "Legislative JSON payload (use as-is without reformatting):",
            f"{examples_text}Legislative JSON payload (use as-is without reformatting):"
        )
    else:
        # Insert at the end
        prompt = prompt + "\n\n" + examples_text
    
    return prompt


def _normalise_json_text(text: str) -> str:
    """Normalize JSON text by removing code fences and quotes."""
    cleaned = text.replace("```json", "").replace("```", "")
    cleaned = cleaned.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned[3:].strip()
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3].strip()
    while cleaned and cleaned[0] in {'"', "'"} and cleaned[-1] == cleaned[0]:
        cleaned = cleaned[1:-1].strip()
    return cleaned


def call_model(
    *,
    model: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
    api_key: Optional[str] = None
) -> str:
    """Call OpenAI API with the prompt."""
    load_dotenv()
    
    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        raise ValueError("OpenAI API key is required via --api-key or OPENAI_API_KEY env var.")
    
    client = OpenAI(api_key=key)
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    
    return response.choices[0].message.content.strip()


def annotate_with_fewshot(
    *,
    json_path: Path,
    unified_csv: str,
    model: str,
    prompt_path: Path = DEFAULT_PROMPT_PATH,
    api_key: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 4000,
    num_examples: int = 3,
    legislation_id: Optional[str] = None
) -> tuple[str, Optional[Any]]:
    """Annotate a document using few-shot learning."""
    # Load examples
    examples = select_example_annotations(
        unified_csv,
        num_examples=num_examples,
        exclude_legislation_id=legislation_id
    )
    
    if not examples:
        LOGGER.warning("No examples found, falling back to zero-shot")
    
    # Load template and document
    template = read_prompt_template(prompt_path)
    document_json = load_document_payload(json_path)
    
    # Build prompt with examples
    user_prompt = build_fewshot_prompt(
        template,
        document_json,
        json_path,
        examples
    )
    
    LOGGER.info(f"Submitting {json_path.name} to model {model} with {len(examples)} examples")
    
    # Call model
    raw_response = call_model(
        model=model,
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=api_key
    )
    
    # Parse response
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


def run_cli(argv: Optional[List[str]] = None) -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Few-shot annotation over legislative JSON payloads")
    parser.add_argument("json_path", type=Path, help="Path to the legislative JSON file")
    parser.add_argument("unified_csv", type=Path, help="Path to unified annotations CSV for examples")
    parser.add_argument("--model", default="gpt-4o", help="Chat model to call")
    parser.add_argument("--prompt-path", type=Path, default=DEFAULT_PROMPT_PATH, help="Path to the prompt template")
    parser.add_argument("--api-key", help="OpenAI API key (default: OPENAI_API_KEY env var)")
    parser.add_argument("--temperature", type=float, default=0.2, help="Sampling temperature")
    parser.add_argument("--max-tokens", type=int, default=4000, help="Maximum tokens in the response")
    parser.add_argument("--num-examples", type=int, default=3, help="Number of example annotations to include")
    parser.add_argument("--legislation-id", help="Legislation ID to exclude from examples")
    parser.add_argument("--output", type=Path, help="Optional path to write the parsed JSON output")
    parser.add_argument("--raw-output", type=Path, help="Always write the raw model response to this path")
    
    args = parser.parse_args(args=argv)
    
    raw_response, parsed = annotate_with_fewshot(
        json_path=args.json_path,
        unified_csv=str(args.unified_csv),
        model=args.model,
        prompt_path=args.prompt_path,
        api_key=args.api_key,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        num_examples=args.num_examples,
        legislation_id=args.legislation_id
    )
    
    # Write outputs
    if parsed is not None and args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8") as f:
            json.dump(parsed, f, ensure_ascii=False, indent=2)
        LOGGER.info(f"Saved parsed JSON to {args.output}")
    
    if args.raw_output is not None:
        args.raw_output.parent.mkdir(parents=True, exist_ok=True)
        with args.raw_output.open("w", encoding="utf-8") as f:
            f.write(raw_response)
        LOGGER.info(f"Saved raw response to {args.raw_output}")


if __name__ == "__main__":
    run_cli()

