import argparse
import csv
import json
import os
from collections import defaultdict
from typing import Dict, List, Optional, Set

from util import normalize_hierarchy_file

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUTPUTS_DIR = os.path.join(CURRENT_DIR, "Children Act 1989", "outputs")
DEFAULT_HIERARCHY_JSON = os.path.join(
    CURRENT_DIR, "Children Act 1989", "1989_41_sections_hierarchy.json"
)
DEFAULT_BASE_URL = "https://www.legislation.gov.uk/ukpga/1989/41"
DEFAULT_OUTPUT_CSV = os.path.join(
    CURRENT_DIR, "Children Act 1989", "outputs", "sections_combined.csv"
)


def get_section_id_from_url(section_url: Optional[str], base_url: str) -> Optional[str]:
    """Convert a legislation URL back into a `section-#` style identifier."""
    if not section_url or not base_url:
        return None

    if section_url.startswith(base_url):
        path = section_url[len(base_url):].strip("/")
        if not path:
            return None
        parts = path.split("/")
        section_id_parts = []
        i = 0
        while i < len(parts):
            if i + 1 < len(parts):
                section_id_parts.append(f"{parts[i]}-{parts[i + 1]}")
                i += 2
            else:
                section_id_parts.append(parts[i])
                i += 1
        return "/".join(section_id_parts)
    return None


def find_section_in_hierarchy(section_id: str, data: Dict) -> Optional[Dict]:
    """Recursively locate the dictionary for a given section identifier."""
    if not section_id or not isinstance(data, dict):
        return None

    if "/" in section_id:
        parts = section_id.split("/")
        current_id = parts[0]
        remaining = "/".join(parts[1:])
    else:
        current_id = section_id
        remaining = None

    if current_id in data:
        section_data = data[current_id]
        if remaining:
            if "subsections" in section_data:
                result = find_section_in_hierarchy(remaining, section_data["subsections"])
                if result:
                    return result
            if "subitems" in section_data:
                result = find_section_in_hierarchy(remaining, section_data["subitems"])
                if result:
                    return result
        else:
            return section_data

    if "sections" in data:
        result = find_section_in_hierarchy(section_id, data["sections"])
        if result:
            return result

    if "parts" in data:
        for _, part_data in data["parts"].items():
            result = find_section_in_hierarchy(section_id, part_data)
            if result:
                return result

    if "chapters" in data:
        for _, chapter_data in data["chapters"].items():
            result = find_section_in_hierarchy(section_id, chapter_data)
            if result:
                return result

    if "subsections" in data:
        result = find_section_in_hierarchy(section_id, data["subsections"])
        if result:
            return result

    if "subitems" in data:
        result = find_section_in_hierarchy(section_id, data["subitems"])
        if result:
            return result

    return None


def extract_text_from_section(section_data: Dict) -> str:
    """Flatten a section dictionary into a single text blob."""
    if not isinstance(section_data, dict):
        return ""

    text_parts: List[str] = []

    for key in ("number", "title", "content", "additional_content"):
        value = section_data.get(key)
        if isinstance(value, list):
            text_parts.extend(str(item) for item in value if item)
        elif isinstance(value, str):
            text_parts.append(value)

    if "lists" in section_data:
        for list_data in section_data["lists"]:
            items = list_data.get("items")
            if isinstance(items, list):
                text_parts.extend(str(item) for item in items if item)

    for key in ("subsections", "subitems"):
        if key in section_data and isinstance(section_data[key], dict):
            for _, child in section_data[key].items():
                child_text = extract_text_from_section(child)
                if child_text:
                    text_parts.append(child_text)

    return " ".join(part for part in text_parts if part)


def collect_section_ids(annotation: Dict, base_url: str) -> Set[str]:
    """Return the set of section identifiers referenced by an annotation."""
    section_ids: Set[str] = set()

    main_section = annotation.get("main_section")
    sid = get_section_id_from_url(main_section, base_url)
    if sid:
        section_ids.add(sid)

    for condition in annotation.get("conditions", []):
        cond_sid = get_section_id_from_url(condition.get("section"), base_url)
        if cond_sid:
            section_ids.add(cond_sid)

    return section_ids


def aggregate_annotations(outputs_dir: str, hierarchy_json: Dict, base_url: str):
    """Aggregate annotations per section across all CSV files in `outputs_dir`."""
    section_entries: Dict[str, Dict[str, List]] = defaultdict(lambda: {
        "annotations_json": [],
        "annotations_text": []
    })

    csv_files = sorted(
        file for file in os.listdir(outputs_dir)
        if file.lower().endswith(".csv")
    )

    for csv_file in csv_files:
        csv_path = os.path.join(outputs_dir, csv_file)
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                output_raw = (row.get("output") or "").strip()
                if not output_raw:
                    continue
                try:
                    annotation = json.loads(output_raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(annotation, dict) and annotation.get("error"):
                    continue

                section_ids = collect_section_ids(annotation, base_url)
                if not section_ids:
                    continue

                input_text = (row.get("input") or "").strip()
                for sid in section_ids:
                    section_entries[sid]["annotations_json"].append(annotation)
                    section_entries[sid]["annotations_text"].append(input_text)

    section_payload_cache: Dict[str, Dict[str, str]] = {}

    aggregated_rows = []
    for section_id in sorted(section_entries.keys()):
        if section_id not in section_payload_cache:
            section_data = find_section_in_hierarchy(section_id, hierarchy_json)
            section_payload_cache[section_id] = {
                "section_id": section_id,
                "text": extract_text_from_section(section_data) if section_data else ""
            }
        payload = section_payload_cache[section_id]

        aggregated_rows.append({
            "input": section_id,
            "section_text": json.dumps(payload, ensure_ascii=False),
            "output_json": json.dumps(section_entries[section_id]["annotations_json"], ensure_ascii=False),
            "output_text": json.dumps(section_entries[section_id]["annotations_text"], ensure_ascii=False)
        })

    return aggregated_rows


def write_aggregated_csv(rows: List[Dict[str, str]], output_csv: str):
    os.makedirs(os.path.dirname(output_csv), exist_ok=True)
    with open(output_csv, "w", encoding="utf-8", newline="") as f:
        fieldnames = ["input", "section_text", "output_json", "output_text"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def parse_args():
    parser = argparse.ArgumentParser(description="Aggregate matched annotations per section.")
    parser.add_argument(
        "outputs_dir",
        nargs="?",
        default=DEFAULT_OUTPUTS_DIR,
        help=f"Directory containing Chunk*.csv files from annotation matcher (default: {DEFAULT_OUTPUTS_DIR}).",
    )
    parser.add_argument(
        "hierarchy_json",
        nargs="?",
        default=DEFAULT_HIERARCHY_JSON,
        help="Path to the hierarchy JSON file for the Act/Part.",
    )
    parser.add_argument(
        "base_url",
        nargs="?",
        default=DEFAULT_BASE_URL,
        help=f"Base legislation URL (default: {DEFAULT_BASE_URL}).",
    )
    parser.add_argument(
        "output_csv",
        nargs="?",
        default=DEFAULT_OUTPUT_CSV,
        help="Path to write the aggregated CSV (default: sections_combined.csv next to outputs).",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    normalized_hierarchy_path = normalize_hierarchy_file(args.hierarchy_json)
    with open(normalized_hierarchy_path, "r", encoding="utf-8") as f:
        hierarchy_json = json.load(f)

    rows = aggregate_annotations(args.outputs_dir, hierarchy_json, args.base_url)
    write_aggregated_csv(rows, args.output_csv)
    print(f"Aggregated {len(rows)} sections into {args.output_csv}")


if __name__ == "__main__":
    main()
