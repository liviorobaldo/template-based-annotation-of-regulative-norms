"""
Create act_sections.csv file that maps section_id to section_json for each act.
This makes it easy to find sections without searching through multiple chunk files.

Output CSV format:
- section_id: e.g., "section-1", "section-10"
- section_json: JSON string representation of the section
"""
import argparse
import csv
import json
import logging
from pathlib import Path
from typing import Dict, List

LOGGER = logging.getLogger("create_act_sections_csv")
if not LOGGER.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def extract_all_sections_from_hierarchy(hierarchy_data: Dict, act_id: str) -> Dict[str, Dict]:
    """
    Extract only top-level sections from hierarchy JSON (e.g., section-1, section-10).
    Excludes subsections like section-1-1, section-1-2, etc.
    
    Returns: {section_id: section_data}
    """
    sections = {}
    
    def is_top_level_section(section_id: str) -> bool:
        """Check if section_id is a top-level section (e.g., section-1, section-10, not section-1-1)."""
        if not section_id.startswith('section-'):
            return False
        # Top-level sections match pattern: section-{number} or section-{number}{letter}
        # Examples: section-1, section-10, section-11A, section-11D
        # Not: section-1-1, section-1-2, section-10-1
        parts = section_id.split('-')
        if len(parts) == 2:  # section-{number}
            return True
        elif len(parts) == 3 and parts[2].isdigit():  # section-{number}-{digit} (subsection)
            return False
        elif len(parts) == 2 and not parts[1].isdigit() and not parts[1][0].isdigit():
            # section-{non-numeric} - might be valid
            return True
        # section-{number}{letter} like section-11A
        if len(parts) == 2 and parts[1] and parts[1][0].isdigit():
            return True
        return False
    
    def extract_from_parts_sections(data: Dict):
        """Extract sections from parts -> sections structure."""
        if 'parts' in data and isinstance(data['parts'], dict):
            for part_key, part_data in data['parts'].items():
                if isinstance(part_data, dict) and 'sections' in part_data:
                    if isinstance(part_data['sections'], dict):
                        for section_id, section_data in part_data['sections'].items():
                            if is_top_level_section(section_id):
                                sections[section_id] = section_data
                                LOGGER.debug(f"Found top-level section: {section_id}")
        
        # Also check direct sections
        if 'sections' in data and isinstance(data['sections'], dict):
            for section_id, section_data in data['sections'].items():
                if is_top_level_section(section_id):
                    sections[section_id] = section_data
                    LOGGER.debug(f"Found top-level section (direct): {section_id}")
    
    extract_from_parts_sections(hierarchy_data)
    return sections


def process_act_chunks(act_dir: Path, act_id: str) -> Dict[str, Dict]:
    """
    Process all chunk JSON files for an act and extract all sections.
    
    Returns: {section_id: section_data}
    """
    all_sections = {}
    
    # Find all chunk JSON files
    chunk_files = sorted(act_dir.glob(f"*{act_id}*chunk*.json"))
    
    if not chunk_files:
        LOGGER.warning(f"No chunk files found for {act_id} in {act_dir}")
        return all_sections
    
    LOGGER.info(f"Processing {len(chunk_files)} chunk files for {act_id}")
    
    for chunk_file in chunk_files:
        LOGGER.info(f"  Processing {chunk_file.name}")
        try:
            with open(chunk_file, 'r', encoding='utf-8') as f:
                chunk_data = json.load(f)
            
            # Extract sections from this chunk
            chunk_sections = extract_all_sections_from_hierarchy(chunk_data, act_id)
            
            # Merge into all_sections (later chunks may override earlier ones)
            for section_id, section_data in chunk_sections.items():
                all_sections[section_id] = section_data
            
            LOGGER.info(f"    Found {len(chunk_sections)} sections in {chunk_file.name}")
        
        except Exception as e:
            LOGGER.error(f"    Error processing {chunk_file.name}: {e}")
            continue
    
    return all_sections


def create_act_sections_csv(act_dir: Path, act_id: str, output_csv: Path):
    """
    Create CSV file mapping section_id to section_json for an act.
    
    Args:
        act_dir: Directory containing chunk JSON files
        act_id: Act identifier (e.g., "1989_41")
        output_csv: Path to output CSV file
    """
    # Extract all sections from chunk files
    sections = process_act_chunks(act_dir, act_id)
    
    if not sections:
        LOGGER.warning(f"No sections found for {act_id}")
        return
    
    LOGGER.info(f"Total unique sections found: {len(sections)}")
    
    # Create CSV
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_csv, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['section_id', 'section_json'])
        writer.writeheader()
        
        for section_id in sorted(sections.keys()):
            section_json_str = json.dumps(sections[section_id], ensure_ascii=False)
            writer.writerow({
                'section_id': section_id,
                'section_json': section_json_str
            })
    
    LOGGER.info(f"Created {output_csv} with {len(sections)} sections")


def process_all_acts(root_dir: Path, output_dir: Path):
    """Process all acts in the root directory."""
    root_dir = Path(root_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Find all act directories
    act_dirs = []
    for item in root_dir.iterdir():
        if item.is_dir() and item.name not in ['outputs', '__pycache__']:
            # Try to find chunk files to identify acts
            chunk_files = list(item.glob("*chunk*.json"))
            if chunk_files:
                act_dirs.append(item)
    
    LOGGER.info(f"Found {len(act_dirs)} act directories")
    
    for act_dir in act_dirs:
        # Try to extract act ID from chunk file names
        chunk_files = list(act_dir.glob("*chunk*.json"))
        if not chunk_files:
            continue
        
        # Extract act ID from first chunk file (e.g., "1989_41" from "1989_41_chunk_1_sections_hierarchy.json")
        first_chunk = chunk_files[0].name
        parts = first_chunk.split('_')
        if len(parts) >= 2:
            act_id = f"{parts[0]}_{parts[1]}"
        else:
            act_id = act_dir.name.replace(' ', '_')
        
        LOGGER.info(f"\nProcessing act: {act_dir.name} (ID: {act_id})")
        
        output_csv = output_dir / f"{act_id}_sections.csv"
        create_act_sections_csv(act_dir, act_id, output_csv)


def main():
    parser = argparse.ArgumentParser(
        description="Create act_sections.csv files mapping section_id to section_json"
    )
    parser.add_argument(
        "--act-dir",
        type=Path,
        help="Directory containing chunk JSON files for a specific act"
    )
    parser.add_argument(
        "--act-id",
        type=str,
        help="Act identifier (e.g., '1989_41'). Required if --act-dir is specified"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output CSV file path (required if --act-dir is specified)"
    )
    parser.add_argument(
        "--root-dir",
        type=Path,
        default=Path(__file__).parent,
        help="Root directory containing act folders (default: script directory)"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent / "sections_csv",
        help="Output directory for CSV files (default: sections_csv/)"
    )
    
    args = parser.parse_args()
    
    if args.act_dir:
        # Process single act
        if not args.act_id:
            parser.error("--act-id is required when --act-dir is specified")
        if not args.output:
            parser.error("--output is required when --act-dir is specified")
        
        create_act_sections_csv(args.act_dir, args.act_id, args.output)
    else:
        # Process all acts
        process_all_acts(args.root_dir, args.output_dir)


if __name__ == "__main__":
    main()

