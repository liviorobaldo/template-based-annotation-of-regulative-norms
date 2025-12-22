"""
Create JSONL training and test files for fine-tuning.

This script:
1. Reads sections from act_sections.csv files
2. Reads annotations from unified_annotations.csv
3. Splits into 80/20 train/test (ensuring experimental sections go to test)
4. Creates JSONL files where each line is:
   {
     "messages": [
       {"role": "system", "content": "..."},
       {"role": "user", "content": "<section_json>"},
       {"role": "assistant", "content": "<annotations_json>"}
     ]
   }
"""
import argparse
import csv
import json
import logging
import random
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

LOGGER = logging.getLogger("create_training_data")
if not LOGGER.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def load_sections_from_hierarchy_json(hierarchy_dir: Path, legislation_ids: set) -> Dict[str, Dict]:
    """
    Load section JSON from hierarchy JSON files based on legislation_ids.
    
    Args:
        hierarchy_dir: Directory containing hierarchy JSON files (chunk files)
        legislation_ids: Set of legislation_ids to load
    
    Returns: {legislation_id: section_json_dict}
    """
    sections = {}
    
    # Group legislation_ids by act_id
    act_sections: Dict[str, List[str]] = defaultdict(list)
    for leg_id in legislation_ids:
        act_id = '_'.join(leg_id.split('_')[:2])
        section_id = '_'.join(leg_id.split('_')[2:])
        act_sections[act_id].append((leg_id, section_id))
    
    # Load from hierarchy JSON files
    for act_id, section_list in act_sections.items():
        LOGGER.info(f"Loading sections for act {act_id} from hierarchy JSON files...")
        
        # Find all chunk JSON files for this act
        chunk_files = sorted(hierarchy_dir.rglob(f"*{act_id}*chunk*.json"))
        
        if not chunk_files:
            LOGGER.warning(f"No chunk files found for {act_id}")
            continue
        
        # Load all chunk files and extract sections
        # We need to search through all chunk files for each section
        for leg_id, section_id in section_list:
            if leg_id in sections:
                continue  # Already found
            
            # Try each chunk file until we find the section
            for chunk_file in chunk_files:
                try:
                    with open(chunk_file, 'r', encoding='utf-8') as f:
                        hierarchy_data = json.load(f)
                    
                    section_json = extract_section_from_hierarchy(hierarchy_data, section_id)
                    if section_json:
                        sections[leg_id] = section_json
                        break  # Found it, move to next section
                except Exception as e:
                    LOGGER.debug(f"Error loading {chunk_file.name}: {e}")
                    continue
            
            if leg_id not in sections:
                LOGGER.warning(f"Could not find section {section_id} for {leg_id} in any chunk file")
    
    LOGGER.info(f"Loaded {len(sections)} sections from hierarchy JSON files")
    
    # Log which sections were requested but not found
    requested_count = sum(len(section_list) for section_list in act_sections.values())
    if len(sections) < requested_count:
        missing = requested_count - len(sections)
        LOGGER.warning(f"{missing} sections from unified CSV were not found in hierarchy JSON files")
    
    return sections


def extract_section_from_hierarchy(hierarchy_data: Dict, section_id: str) -> Optional[Dict]:
    """Extract a single section from hierarchy JSON."""
    def find_section_recursive(data: Dict) -> Optional[Dict]:
        """Recursively search for section in hierarchy."""
        if not isinstance(data, dict):
            return None
        
        # Check if this is the section we're looking for (top-level key)
        if section_id in data:
            return data[section_id]
        
        # Check parts -> sections structure
        if 'parts' in data:
            for part_key, part_data in data['parts'].items():
                if isinstance(part_data, dict):
                    # Check if sections are directly in part
                    if 'sections' in part_data:
                        if section_id in part_data['sections']:
                            return part_data['sections'][section_id]
                    # Check if chapters are in part
                    if 'chapters' in part_data:
                        for chapter_key, chapter_data in part_data['chapters'].items():
                            if isinstance(chapter_data, dict) and 'sections' in chapter_data:
                                if section_id in chapter_data['sections']:
                                    return chapter_data['sections'][section_id]
                    # Recursively search in part
                    result = find_section_recursive(part_data)
                    if result:
                        return result
        
        # Check direct sections
        if 'sections' in data and section_id in data['sections']:
            return data['sections'][section_id]
        
        # Check chapters -> sections
        if 'chapters' in data:
            for chapter_key, chapter_data in data['chapters'].items():
                if isinstance(chapter_data, dict) and 'sections' in chapter_data:
                    if section_id in chapter_data['sections']:
                        return chapter_data['sections'][section_id]
        
        return None
    
    return find_section_recursive(hierarchy_data)


def load_annotations_from_unified_csv(unified_csv_path: Path) -> Dict[str, List[Dict]]:
    """
    Load annotations from unified_annotations.csv.
    
    Returns: {legislation_id: [list of annotation dicts]}
    """
    annotations = {}
    
    with open(unified_csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            legislation_id = row['legislation_id']
            annotations_json = json.loads(row['annotations'])
            annotations[legislation_id] = annotations_json
    
    LOGGER.info(f"Loaded annotations for {len(annotations)} sections")
    return annotations


def get_experimental_sections(unified_csv_path: Path, limit: int = 10) -> set:
    """Get the first N sections that were used in experiments."""
    experimental = set()
    
    with open(unified_csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if i >= limit:
                break
            experimental.add(row['legislation_id'])
    
    return experimental


def create_jsonl_entry(section_json: Dict, annotations: List[Dict], prompt_template: str) -> Dict:
    """
    Create a single JSONL entry in OpenAI fine-tuning format.
    
    Args:
        section_json: The section JSON from act_sections.csv
        annotations: List of annotation dicts from unified_annotations.csv
        prompt_template: The prompt template to use
    
    Returns:
        Dict in OpenAI fine-tuning format
    """
    # Format section JSON as string
    section_json_str = json.dumps(section_json, ensure_ascii=False, indent=2)
    
    # Format annotations as JSON array string
    annotations_json_str = json.dumps(annotations, ensure_ascii=False, indent=2)
    
    # Build user prompt (replace placeholders in template)
    user_prompt = prompt_template.replace("{{DOCUMENT_JSON}}", section_json_str)
    user_prompt = user_prompt.replace("{{SOURCE_PATH}}", "training_data")
    
    # Create messages
    messages = [
        {
            "role": "system",
            "content": "You are an expert legal annotator who extracts and formats obligations, "
                      "prohibitions, and permissions from legislative text. Respond with precise "
                      "and well-structured JSON only."
        },
        {
            "role": "user",
            "content": user_prompt
        },
        {
            "role": "assistant",
            "content": annotations_json_str
        }
    ]
    
    return {"messages": messages}


def split_train_test(
    all_sections: Dict[str, Dict],
    all_annotations: Dict[str, List[Dict]],
    experimental_sections: set,
    train_ratio: float = 0.8
) -> Tuple[List[str], List[str]]:
    """
    Split sections into train and test sets.
    
    Args:
        all_sections: All available sections
        all_annotations: All available annotations
        experimental_sections: Sections that were used in experiments (go to test)
        train_ratio: Ratio for training set (default 0.8)
    
    Returns:
        (train_section_ids, test_section_ids)
    """
    # Get sections that have both section JSON and annotations
    valid_sections = set(all_sections.keys()) & set(all_annotations.keys())
    
    # Log sections that are in annotations but not in hierarchy JSON
    annotations_only = set(all_annotations.keys()) - set(all_sections.keys())
    if annotations_only:
        LOGGER.warning(f"{len(annotations_only)} sections in unified CSV but not in hierarchy JSON (will be skipped):")
        LOGGER.warning(f"  Examples: {sorted(list(annotations_only))[:10]}")
    
    # Log sections that are in hierarchy JSON but not in annotations
    sections_only = set(all_sections.keys()) - set(all_annotations.keys())
    if sections_only:
        LOGGER.info(f"{len(sections_only)} sections in hierarchy JSON but not in unified CSV (no annotations available)")
    
    # Remove experimental sections from valid set (they go to test)
    valid_sections = valid_sections - experimental_sections
    
    # Split remaining sections
    valid_list = list(valid_sections)
    random.seed(42)  # For reproducibility
    random.shuffle(valid_list)
    
    split_idx = int(len(valid_list) * train_ratio)
    train_sections = valid_list[:split_idx]
    test_sections = valid_list[split_idx:]
    
    # Add experimental sections to test set
    experimental_in_test = [s for s in experimental_sections if s in all_sections and s in all_annotations]
    test_sections.extend(experimental_in_test)
    
    LOGGER.info(f"Train set: {len(train_sections)} sections")
    LOGGER.info(f"Test set: {len(test_sections)} sections ({len(experimental_in_test)} experimental + {len(test_sections) - len(experimental_in_test)} others)")
    
    return train_sections, test_sections


def create_jsonl_file(
    section_ids: List[str],
    all_sections: Dict[str, Dict],
    all_annotations: Dict[str, List[Dict]],
    prompt_template: str,
    output_path: Path
):
    """Create a JSONL file from section IDs."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        for section_id in section_ids:
            section_json = all_sections[section_id]
            annotations = all_annotations[section_id]
            
            entry = create_jsonl_entry(section_json, annotations, prompt_template)
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    
    LOGGER.info(f"Created {output_path} with {len(section_ids)} entries")


def main():
    parser = argparse.ArgumentParser(description="Create JSONL training and test files")
    parser.add_argument(
        "--hierarchy-dir",
        type=Path,
        default=Path(__file__).parent.parent / "Obligation_prohibition_picking_context",
        help="Directory containing hierarchy JSON files (chunk files)"
    )
    parser.add_argument(
        "--unified-csv",
        type=Path,
        default=Path(__file__).parent / "data" / "unified_annotations.csv",
        help="Path to unified_annotations.csv"
    )
    parser.add_argument(
        "--prompt-path",
        type=Path,
        default=Path(__file__).parent / "prompt.txt",
        help="Path to prompt template"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent / "training_data",
        help="Output directory for JSONL files"
    )
    parser.add_argument(
        "--train-ratio",
        type=float,
        default=0.8,
        help="Ratio for training set (default: 0.8)"
    )
    parser.add_argument(
        "--experimental-limit",
        type=int,
        default=10,
        help="Number of experimental sections to put in test set (default: 10)"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42)"
    )
    
    args = parser.parse_args()
    
    # Set random seed
    random.seed(args.seed)
    
    # Load prompt template
    prompt_template = args.prompt_path.read_text(encoding='utf-8')
    
    # Load annotations from unified CSV first (this is our source of truth)
    LOGGER.info("Loading annotations from unified CSV...")
    all_annotations = load_annotations_from_unified_csv(args.unified_csv)
    
    # Get experimental sections
    experimental_sections = get_experimental_sections(args.unified_csv, limit=args.experimental_limit)
    LOGGER.info(f"Experimental sections (will go to test set): {len(experimental_sections)}")
    
    # Get all legislation_ids from annotations
    all_legislation_ids = set(all_annotations.keys())
    
    # Load section JSON from hierarchy JSON files (only for sections that have annotations)
    LOGGER.info("Loading section JSON from hierarchy JSON files...")
    all_sections = load_sections_from_hierarchy_json(args.hierarchy_dir, all_legislation_ids)
    
    # Split into train/test
    train_sections, test_sections = split_train_test(
        all_sections,
        all_annotations,
        experimental_sections,
        train_ratio=args.train_ratio
    )
    
    # Create JSONL files
    train_path = args.output_dir / "train.jsonl"
    test_path = args.output_dir / "test.jsonl"
    
    LOGGER.info(f"Creating training JSONL file: {train_path}")
    create_jsonl_file(train_sections, all_sections, all_annotations, prompt_template, train_path)
    
    LOGGER.info(f"Creating test JSONL file: {test_path}")
    create_jsonl_file(test_sections, all_sections, all_annotations, prompt_template, test_path)
    
    # Save section IDs for reference
    train_ids_path = args.output_dir / "train_section_ids.txt"
    test_ids_path = args.output_dir / "test_section_ids.txt"
    
    with open(train_ids_path, 'w', encoding='utf-8') as f:
        for section_id in sorted(train_sections):
            f.write(f"{section_id}\n")
    
    with open(test_ids_path, 'w', encoding='utf-8') as f:
        for section_id in sorted(test_sections):
            f.write(f"{section_id}\n")
    
    LOGGER.info(f"\n{'='*80}")
    LOGGER.info("Training data creation complete!")
    LOGGER.info(f"Train set: {len(train_sections)} sections -> {train_path}")
    LOGGER.info(f"Test set: {len(test_sections)} sections -> {test_path}")
    LOGGER.info(f"{'='*80}")


if __name__ == "__main__":
    main()

