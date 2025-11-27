import argparse
import json
from typing import Any, Dict, Optional
from xml.etree.ElementTree import Element, SubElement

def convert_to_html(text,root):
    """
    Convert text to XML Element format, handling various structures like numbered points and lettered lists.
    
    Args:
        text (str): The text to convert
        
    Returns:
        Element: Root XML element containing the formatted text
    """
    if not text:
        return text

    #root = Element()
    numbered_points = []
    current_point = ''
    
    lines = text.split('.')
    i = 0
    while i < len(lines):
        if i < len(lines) - 1 and lines[i].strip() and lines[i][-1].isdigit():
            point = lines[i] + '.' + lines[i + 1]
            numbered_points.append(point.strip())
            i += 2
        elif i == 0:
            current_point = lines[i]
            i += 1
        else:
            if current_point:
                current_point += '.' + lines[i]
            else:
                current_point = lines[i]
            i += 1
    
    if current_point.strip():
        numbered_points.insert(0, current_point.strip())
    
    if len(numbered_points) <= 1:
        if any(f"({char})" in text.lower() for char in 'abcdefghijklmnopqrstuvwxyz'):
            if '(a)' in text:
                parts = text.split('(a)')
                main_text = parts[0].strip()
                list_content = '(a)' + parts[1]
                list_items = []
                current_item = ''
                
                for char in list_content:
                    current_item += char
                    if char == ',' or char == ';':
                        list_items.append(current_item.strip())
                        current_item = ''
                
                if current_item:
                    list_items.append(current_item.strip())
                
                p = SubElement(root, 'p')
                p.text = main_text
                ul = SubElement(root, 'ul')
                for item in list_items:
                    li = SubElement(ul, 'li')
                    li.text = item
                return root
        
        p = SubElement(root, 'p')
        p.text = text
        return root
    
    for point in numbered_points:
        if '(a)' in point.lower():
            parts = point.split('(a)')
            number_part = parts[0].strip()
            p = SubElement(root, 'p')
            p.text = number_part
            
            ul = SubElement(root, 'ul')
            remaining_text = '(a)' + parts[1]
            letter_items = []
            current_item = ''
            
            for i in range(len(remaining_text)):
                current_item += remaining_text[i]
                if i < len(remaining_text) - 2 and remaining_text[i+1] == '(' and remaining_text[i+2].isalpha():
                    letter_items.append(current_item.strip())
                    current_item = ''
            
            if current_item:
                letter_items.append(current_item.strip())
            
            for item in letter_items:
                li = SubElement(ul, 'li')
                li.text = item
        else:
            p = SubElement(root, 'p')
            p.text = point
    
    return root


# -----------------------------------------------------------------------------
# Hierarchy normalization utilities
# -----------------------------------------------------------------------------

_COLLECTION_KEYS = {"parts", "chapters", "sections", "subsections", "subitems"}


def _normalize_identifier_component(component: str) -> str:
    """Normalize a single identifier component by removing empty hyphen chunks."""
    if not isinstance(component, str):
        return component
    stripped = component.strip()
    if not stripped:
        return component
    chunks = [chunk for chunk in stripped.split('-') if chunk]
    if not chunks:
        return stripped
    prefix = chunks[0]
    suffix = chunks[1:]
    normalized = '-'.join([prefix] + suffix) if suffix else prefix
    return normalized


def _normalize_identifier(identifier: str) -> str:
    """Normalize identifiers that may include `/` path separators."""
    if not isinstance(identifier, str):
        return identifier
    parts = identifier.split('/')
    normalized_parts = [_normalize_identifier_component(part) for part in parts]
    return '/'.join(normalized_parts)


def _normalize_number_field(value: str) -> str:
    """Normalize number strings like '-25-' -> '25'."""
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        return value
    normalized = stripped.strip('-')
    return normalized or stripped


def _normalize_structure(node: Any) -> Any:
    """Recursively normalize identifiers inside a hierarchy dictionary."""
    if isinstance(node, dict):
        normalized_dict: Dict[Any, Any] = {}
        for key, value in node.items():
            if key in _COLLECTION_KEYS and isinstance(value, dict):
                normalized_children: Dict[Any, Any] = {}
                for child_key, child_value in value.items():
                    normalized_key = _normalize_identifier(child_key)
                    normalized_children[normalized_key] = _normalize_structure(child_value)
                normalized_dict[key] = normalized_children
            elif key == "number" and isinstance(value, str):
                normalized_dict[key] = _normalize_number_field(value)
            else:
                normalized_dict[key] = _normalize_structure(value)
        return normalized_dict
    if isinstance(node, list):
        return [_normalize_structure(item) for item in node]
    return node


def normalize_hierarchy_file(input_path: str, output_path: Optional[str] = None) -> str:
    """
    Normalize malformed section identifiers/numbers within a hierarchy JSON file.

    Args:
        input_path: Path to the source JSON file.
        output_path: Optional destination. Defaults to overwriting the input file.

    Returns:
        Path to the written JSON file.
    """
    with open(input_path, "r", encoding="utf-8") as src:
        data = json.load(src)

    normalized = _normalize_structure(data)
    target_path = output_path or input_path

    with open(target_path, "w", encoding="utf-8") as dst:
        json.dump(normalized, dst, ensure_ascii=False, indent=2)
        dst.write("\n")

    return target_path


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Utility helpers for annotation tooling.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    normalize_parser = subparsers.add_parser(
        "normalize-hierarchy", help="Fix malformed section identifiers in a hierarchy JSON file."
    )
    normalize_parser.add_argument("input", help="Path to the hierarchy JSON file to normalize.")
    normalize_parser.add_argument(
        "-o",
        "--output",
        help="Optional path for the normalized JSON. Defaults to in-place overwrite.",
    )

    return parser


def _run_cli():
    parser = _build_cli_parser()
    args = parser.parse_args()

    if args.command == "normalize-hierarchy":
        written_path = normalize_hierarchy_file(args.input, args.output)
        print(f"Normalized hierarchy written to {written_path}")


if __name__ == "__main__":
    _run_cli()
# #Testing with all examples
# examples = [
#     "the protected characteristic is marriage or civil partnership, or it is a case of discrimination, harassment or victimisation— (a) that is prohibited by Part 3 (services and public functions), (b) that would be so prohibited but for an express exception.",
#     "I am testing this as well 1. How are you (a)Iam fine (b)I am good (c)I am great. 2. How are you (a)Iam fine (b)I am good (c)I am great.",
#     "A. This is the first point. B. This is the second point (a) with a subpoint (b) and another subpoint.",
#     "(1) This is the first point. (2) This is the second point (a) with a subpoint (b) and another subpoint. (3) This is the third point."
# ]

# # Print results for all examples
# for i, example in enumerate(examples):
#     print(f"\nExample {i+1}:")
#     print(convert_to_html(example))
