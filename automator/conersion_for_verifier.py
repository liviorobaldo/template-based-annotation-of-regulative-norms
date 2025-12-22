"""Convert model JSON output into verifier-friendly text format."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

SEPARATOR_LINE = "------------------------"


def _normalise_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _format_block(annotation: dict) -> List[str]:
    block: List[str] = [SEPARATOR_LINE]

    type_str = _normalise_text(annotation.get("type")).upper() or "UNKNOWN"
    block.append(f"IT IS {type_str}")

    for_part = _normalise_text(annotation.get("for")) or "[missing subject]"
    block.append(f"FOR {for_part}")

    to_part = _normalise_text(annotation.get("to")) or "[missing action]"
    block.append(f"TO {to_part}")

    conditions: Iterable[dict] = annotation.get("conditions") or []
    for condition in conditions:
        cond_type = _normalise_text(condition.get("type")).upper()
        cond_text = _normalise_text(condition.get("text"))
        section = _normalise_text(condition.get("section"))

        pieces: List[str] = []
        if cond_type:
            pieces.append(cond_type)
        if cond_text:
            pieces.append(cond_text)
        if section:
            pieces.append(f"[source: {section}]")

        if pieces:
            block.append(" ".join(pieces))

    return block


def convert_annotations(json_path: Path, *, output_path: Optional[Path] = None) -> str:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Expected a JSON array of annotations.")

    lines: List[str] = []
    for annotation in data:
        if not isinstance(annotation, dict):
            continue
        lines.extend(_format_block(annotation))

    text_output = "\n".join(lines) + ("\n" if lines else "")

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text_output, encoding="utf-8")

    return text_output


def run_cli(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser("Convert JSON annotations for verifier consumption")
    parser.add_argument("json_path", type=Path, help="Path to the model JSON output")
    parser.add_argument("--output", type=Path, help="Write formatted text to this path")
    parser.add_argument("--print", action="store_true", help="Also print the formatted text to stdout")

    args = parser.parse_args(args=argv)
    result = convert_annotations(args.json_path, output_path=args.output)

    if args.print or args.output is None:
        print(result, end="")


if __name__ == "__main__":
    run_cli([
        "output/parsed_1989-41_part1_4o.json",
        "--output", "output/annotation_for_verifier_1989-41_part1_4o.txt",
        "--print",
    ])