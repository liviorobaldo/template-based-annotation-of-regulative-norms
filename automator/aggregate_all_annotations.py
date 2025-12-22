"""
Aggregate all annotated CSV files from all acts into a unified format.
Creates a CSV with legislation-id (act_sectionid) and list of annotations.
"""
import csv
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set


def extract_act_id_from_url(url: str) -> Optional[str]:
    """Extract act identifier from URL.
    
    Examples:
    - https://www.legislation.gov.uk/ukpga/1989/41/section/1 -> 1989_41
    - https://www.legislation.gov.uk/ukpga/2014/6/section/1 -> 2014_6
    """
    if not url or not isinstance(url, str):
        return None
    
    # Extract year and chapter number from URL pattern
    # Pattern: /ukpga/YEAR/CHAPTER/section/...
    parts = url.split('/')
    try:
        ukpga_idx = parts.index('ukpga')
        if ukpga_idx + 2 < len(parts):
            year = parts[ukpga_idx + 1]
            chapter = parts[ukpga_idx + 2]
            return f"{year}_{chapter}"
    except (ValueError, IndexError):
        pass
    
    return None


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


def collect_section_ids_from_annotation(annotation: Dict, base_url: str) -> Set[str]:
    """Return the set of section identifiers referenced by an annotation."""
    section_ids: Set[str] = set()

    main_section = annotation.get("main_section")
    if main_section:
        sid = get_section_id_from_url(main_section, base_url)
        if sid:
            section_ids.add(sid)

    for condition in annotation.get("conditions", []):
        cond_section = condition.get("section")
        if cond_section:
            cond_sid = get_section_id_from_url(cond_section, base_url)
            if cond_sid:
                section_ids.add(cond_sid)

    return section_ids


def infer_base_url_from_annotation(annotation: Dict) -> Optional[str]:
    """Infer base URL from annotation's main_section URL."""
    main_section = annotation.get("main_section")
    if not main_section:
        return None
    
    # Extract base URL: https://www.legislation.gov.uk/ukpga/YEAR/CHAPTER
    parts = main_section.split('/')
    try:
        ukpga_idx = parts.index('ukpga')
        if ukpga_idx + 2 < len(parts):
            base_parts = parts[:ukpga_idx + 3]
            return '/'.join(base_parts)
    except (ValueError, IndexError):
        pass
    
    return None


def find_all_csv_files(root_dir: str) -> List[Path]:
    """Find all CSV files in outputs directories."""
    csv_files = []
    root_path = Path(root_dir).resolve()
    
    if not root_path.exists():
        print(f"Warning: Root directory does not exist: {root_path}")
        return []
    
    print(f"Searching for CSV files in: {root_path}")
    
    # Look for pattern: */outputs/*.csv
    # Exclude aggregated files like "sections_combined.csv"
    excluded_files = {"sections_combined.csv", "unified_annotations.csv"}
    
    for outputs_dir in root_path.rglob("outputs"):
        if outputs_dir.is_dir():
            csv_count = 0
            for csv_file in outputs_dir.glob("*.csv"):
                # Skip aggregated files
                if csv_file.name.lower() in excluded_files:
                    continue
                csv_files.append(csv_file)
                csv_count += 1
            if csv_count > 0:
                print(f"  Found {csv_count} CSV files in {outputs_dir}")
    
    return sorted(csv_files)


def aggregate_all_annotations(root_dir: str, output_csv: str):
    """
    Aggregate all annotations from all CSV files across all acts.
    
    Creates a unified CSV with:
    - legislation_id: format like "1989_41_section-1"
    - annotations: JSON array of all annotations for that section
    """
    # Structure: {legislation_id: [list of annotation dicts]}
    aggregated: Dict[str, List[Dict]] = defaultdict(list)
    
    csv_files = find_all_csv_files(root_dir)
    print(f"Found {len(csv_files)} CSV files to process")
    
    for csv_file in csv_files:
        print(f"Processing {csv_file}")
        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    output_raw = (row.get("output") or "").strip()
                    if not output_raw:
                        continue
                    
                    try:
                        annotation = json.loads(output_raw)
                    except json.JSONDecodeError:
                        continue
                    
                    if not isinstance(annotation, dict):
                        continue
                    
                    # Skip error annotations
                    if annotation.get("error"):
                        continue
                    
                    # Remove _alt_section_urls from annotation
                    if "_alt_section_urls" in annotation:
                        del annotation["_alt_section_urls"]
                    
                    # Infer base URL from annotation
                    base_url = infer_base_url_from_annotation(annotation)
                    if not base_url:
                        continue
                    
                    # Extract act ID
                    act_id = extract_act_id_from_url(base_url)
                    if not act_id:
                        continue
                    
                    # Get section IDs from annotation
                    section_ids = collect_section_ids_from_annotation(annotation, base_url)
                    
                    # Warn if annotation act doesn't match CSV file location (data quality check)
                    csv_act_hint = None
                    csv_path_str = str(csv_file)
                    if "1989" in csv_path_str and "41" in csv_path_str:
                        csv_act_hint = "1989_41"
                    elif "2014" in csv_path_str and "6" in csv_path_str:
                        csv_act_hint = "2014_6"
                    elif "2010" in csv_path_str and "15" in csv_path_str:
                        csv_act_hint = "2010_15"
                    elif "1964" in csv_path_str and "81" in csv_path_str:
                        csv_act_hint = "1964_81"
                    
                    if csv_act_hint and act_id != csv_act_hint:
                        print(f"  WARNING: Annotation in {csv_file.name} references act {act_id} (expected {csv_act_hint})")
                    
                    # Create legislation_id for each section: act_id_section_id
                    for section_id in section_ids:
                        legislation_id = f"{act_id}_{section_id}"
                        aggregated[legislation_id].append(annotation)
        
        except Exception as e:
            print(f"Error processing {csv_file}: {e}")
            continue
    
    # Write aggregated CSV
    os.makedirs(os.path.dirname(output_csv) if os.path.dirname(output_csv) else '.', exist_ok=True)
    
    with open(output_csv, 'w', encoding='utf-8', newline='') as f:
        fieldnames = ['legislation_id', 'annotations']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for legislation_id in sorted(aggregated.keys()):
            annotations_json = json.dumps(aggregated[legislation_id], ensure_ascii=False)
            writer.writerow({
                'legislation_id': legislation_id,
                'annotations': annotations_json
            })
    
    print(f"\nAggregated {len(aggregated)} unique legislation sections")
    print(f"Total annotations: {sum(len(anns) for anns in aggregated.values())}")
    print(f"Output written to: {output_csv}")


if __name__ == "__main__":
    import argparse
    
    # Get script directory for relative path resolution
    script_dir = Path(__file__).parent.resolve()
    project_root = script_dir.parent
    
    parser = argparse.ArgumentParser(
        description="Aggregate all annotated CSV files from all acts into unified format"
    )
    parser.add_argument(
        "--root-dir",
        type=str,
        default=None,
        help="Root directory containing act folders with outputs/ subdirectories (default: ../Obligation_prohibition_picking_context)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output CSV file path (default: automator/data/unified_annotations.csv)"
    )
    
    args = parser.parse_args()
    
    # Set defaults based on script location
    if args.root_dir is None:
        root_dir = str(project_root / "Obligation_prohibition_picking_context")
    else:
        # Resolve relative to current working directory
        root_dir = str(Path(args.root_dir).resolve())
    
    if args.output is None:
        output_csv = str(script_dir / "data" / "unified_annotations.csv")
    else:
        # If output is relative, resolve relative to current working directory
        # If absolute, use as-is
        output_path = Path(args.output)
        if output_path.is_absolute():
            output_csv = str(output_path)
        else:
            output_csv = str(Path.cwd() / output_path)
    
    # Ensure output directory exists
    output_path_obj = Path(output_csv)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"Root directory: {root_dir}")
    print(f"Output file: {output_csv}")
    print()
    
    aggregate_all_annotations(root_dir, output_csv)

