"""
Process a single section: extract section from hierarchy JSON, run zeroshot,
create groundtruth from unified CSV, and verify.
"""
import argparse
import csv
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, Optional

from zeroshot_opeai import annotate_json as annotate_json_zeroshot
from fewshot_openai import annotate_json as annotate_json_fewshot
from conersion_for_verifier import convert_annotations

LOGGER = logging.getLogger("process_single_section")
if not LOGGER.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def extract_section_from_hierarchy(hierarchy_json_path: Path, section_id: str) -> Optional[Dict]:
    """
    Extract a single section from the hierarchy JSON.
    
    Args:
        hierarchy_json_path: Path to the full hierarchy JSON file
        section_id: Section identifier like "section-1" or "section-10"
    
    Returns:
        Dictionary containing just that section, or None if not found
    """
    with open(hierarchy_json_path, 'r', encoding='utf-8') as f:
        full_hierarchy = json.load(f)
    
    # Recursively search for the section
    def find_section(data: Dict, target_id: str) -> Optional[Dict]:
        """Recursively search for a section by ID."""
        if isinstance(data, dict):
            # Check if this is the section we're looking for (check key or id field)
            if 'id' in data and data['id'] == target_id:
                return data
            if 'section_id' in data and data['section_id'] == target_id:
                return data
            
            # Search in nested structures (parts -> sections -> subsections -> subitems)
            for key in ['parts', 'sections', 'subsections', 'subitems', 'chapters']:
                if key in data and isinstance(data[key], dict):
                    # Check if target_id is a direct key
                    if target_id in data[key]:
                        return data[key][target_id]
                    # Recursively search in nested items
                    for item_id, item_data in data[key].items():
                        result = find_section(item_data, target_id)
                        if result:
                            return result
        
        return None
    
    # Try finding the section
    section = find_section(full_hierarchy, section_id)
    if section:
        return section
    
    # If not found, try direct key lookup in parts/sections
    if isinstance(full_hierarchy, dict):
        # Check parts -> sections structure
        if 'parts' in full_hierarchy:
            for part_key, part_data in full_hierarchy['parts'].items():
                if isinstance(part_data, dict) and 'sections' in part_data:
                    if section_id in part_data['sections']:
                        return part_data['sections'][section_id]
        
        # Check direct sections
        if 'sections' in full_hierarchy and section_id in full_hierarchy['sections']:
            return full_hierarchy['sections'][section_id]
        
        # Check if section_id is a top-level key
        if section_id in full_hierarchy:
            return full_hierarchy[section_id]
    
    LOGGER.warning(f"Section {section_id} not found in hierarchy")
    LOGGER.debug(f"Available top-level keys: {list(full_hierarchy.keys()) if isinstance(full_hierarchy, dict) else 'Not a dict'}")
    return None


def create_section_hierarchy_json(section_data: Dict, section_id: str, output_path: Path):
    """Create a minimal hierarchy JSON containing only the requested section."""
    # Create a structure that mimics the original format
    section_json = {
        section_id: section_data
    }
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(section_json, f, ensure_ascii=False, indent=2)
    
    LOGGER.info(f"Created section JSON at {output_path}")


def get_groundtruth_from_unified_csv(unified_csv_path: Path, legislation_id: str) -> list:
    """Extract groundtruth annotations for a specific legislation ID from unified CSV."""
    with open(unified_csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['legislation_id'] == legislation_id:
                annotations_json = row['annotations']
                try:
                    return json.loads(annotations_json)
                except json.JSONDecodeError:
                    LOGGER.error(f"Failed to parse annotations JSON for {legislation_id}")
                    return []
    
    LOGGER.warning(f"No groundtruth found for {legislation_id}")
    return []


def get_section_from_csv(legislation_id: str, sections_csv_dir: Path) -> Optional[Dict]:
    """
    Get section JSON from act_sections.csv file.
    
    Args:
        legislation_id: Full legislation ID like "1989_41_section-1"
        sections_csv_dir: Directory containing act_sections.csv files
    
    Returns:
        Section data as dict, or None if not found
    """
    # Extract act ID and section ID
    parts = legislation_id.split('_')
    if len(parts) < 3:
        LOGGER.error(f"Invalid legislation_id format: {legislation_id}")
        return None
    
    act_id = f"{parts[0]}_{parts[1]}"  # e.g., "1989_41"
    section_id = '_'.join(parts[2:])  # e.g., "section-1"
    
    # Find the CSV file for this act
    csv_file = sections_csv_dir / f"{act_id}_sections.csv"
    
    if not csv_file.exists():
        # Try searching in subdirectories
        for act_dir in sections_csv_dir.iterdir():
            if act_dir.is_dir():
                potential_csv = act_dir / f"{act_id}_sections.csv"
                if potential_csv.exists():
                    csv_file = potential_csv
                    break
        else:
            LOGGER.error(f"Could not find sections CSV for {act_id}: {csv_file}")
            return None
    
    # Read CSV and find the section
    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row['section_id'] == section_id:
                    section_json_str = row['section_json']
                    return json.loads(section_json_str)
        
        LOGGER.warning(f"Section {section_id} not found in {csv_file.name}")
        return None
    
    except Exception as e:
        LOGGER.error(f"Error reading sections CSV {csv_file}: {e}")
        return None


def process_single_section(
    section_id: str,
    unified_csv_path: Path,
    legislation_id: str,
    output_dir: Path,
    model: str = "gpt-4o-mini",
    api_key: Optional[str] = None,
    sections_csv_dir: Optional[Path] = None,
    method: str = "zeroshot"
):
    """
    Process a single section: extract, annotate, create groundtruth, and verify.
    
    Args:
        section_id: Section ID like "section-1"
        unified_csv_path: Path to unified annotations CSV
        legislation_id: Full legislation ID like "1989_41_section-1"
        output_dir: Directory to save outputs
        model: Model to use
        api_key: OpenAI API key
        sections_csv_dir: Directory containing act_sections.csv files
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    LOGGER.info(f"Processing {legislation_id} (section {section_id})")
    
    # Step 1: Get section from CSV
    if not sections_csv_dir:
        # Default: look in Obligation_prohibition_picking_context directory
        sections_csv_dir = Path(__file__).parent.parent.parent / "Obligation_prohibition_picking_context"
    
    LOGGER.info("Step 1: Extracting section from act_sections.csv...")
    section_data = get_section_from_csv(legislation_id, Path(sections_csv_dir))
    
    if not section_data:
        LOGGER.error(f"Could not find section {section_id} in sections CSV")
        return
    
    # Create temporary JSON file with just this section
    section_json_path = output_dir / f"{legislation_id}_section.json"
    create_section_hierarchy_json(section_data, section_id, section_json_path)
    
    # Step 3: Run annotation (zero-shot or few-shot)
    method_label = "few-shot" if method == "fewshot" else "zero-shot"
    LOGGER.info(f"Step 3: Running {method_label} annotation...")
    
    if method == "fewshot":
        raw_response, parsed = annotate_json_fewshot(
            json_path=section_json_path,
            model=model,
            api_key=api_key,
            temperature=0.2,
            max_tokens=4000,
            num_examples=3
        )
    else:
        raw_response, parsed = annotate_json_zeroshot(
            json_path=section_json_path,
            model=model,
            api_key=api_key,
            temperature=0.2,
            max_tokens=4000
        )
    
    if not parsed:
        LOGGER.error("Failed to parse model response")
        # Save raw response for debugging
        with open(output_dir / f"{legislation_id}_raw_response.txt", 'w', encoding='utf-8') as f:
            f.write(raw_response)
        return
    
    # Save LLM annotations JSON
    llm_json_path = output_dir / f"{legislation_id}_llm_annotations.json"
    with open(llm_json_path, 'w', encoding='utf-8') as f:
        json.dump(parsed, f, ensure_ascii=False, indent=2)
    LOGGER.info(f"Saved LLM annotations to {llm_json_path}")
    
    # Step 4: Convert LLM output to verifier format
    LOGGER.info("Step 4: Converting LLM output to verifier format...")
    llm_text_path = output_dir / f"{legislation_id}_llm_annotations.txt"
    convert_annotations(llm_json_path, output_path=llm_text_path)
    LOGGER.info(f"Saved LLM annotations text to {llm_text_path}")
    
    # Step 5: Get groundtruth from unified CSV
    LOGGER.info("Step 5: Extracting groundtruth from unified CSV...")
    groundtruth_annotations = get_groundtruth_from_unified_csv(unified_csv_path, legislation_id)
    
    if not groundtruth_annotations:
        LOGGER.warning("No groundtruth found - skipping verification")
        return
    
    # Save groundtruth JSON
    groundtruth_json_path = output_dir / f"{legislation_id}_groundtruth.json"
    with open(groundtruth_json_path, 'w', encoding='utf-8') as f:
        json.dump(groundtruth_annotations, f, ensure_ascii=False, indent=2)
    LOGGER.info(f"Saved groundtruth JSON to {groundtruth_json_path}")
    
    # Step 6: Convert groundtruth to verifier format
    LOGGER.info("Step 6: Converting groundtruth to verifier format...")
    groundtruth_text_path = output_dir / f"{legislation_id}_groundtruth.txt"
    convert_annotations(groundtruth_json_path, output_path=groundtruth_text_path)
    LOGGER.info(f"Saved groundtruth text to {groundtruth_text_path}")
    
    # Step 7: Run verifier
    LOGGER.info("Step 7: Running verifier...")
    try:
        # Import verifier
        verifier_path = Path(__file__).parent.parent / "Verifier" / "verifier.py"
        if not verifier_path.exists():
            LOGGER.error(f"Verifier not found at {verifier_path}")
            return
        
        # Copy files to verifier directory temporarily
        import shutil
        verifier_dir = verifier_path.parent
        temp_annotation = verifier_dir / "annotation.txt"
        temp_groundtruth = verifier_dir / "groundtruth1.txt"  # Verifier expects groundtruth1.txt
        
        shutil.copy(llm_text_path, temp_annotation)
        shutil.copy(groundtruth_text_path, temp_groundtruth)
        
        LOGGER.info(f"Copied LLM annotations to {temp_annotation}")
        LOGGER.info(f"Copied groundtruth to {temp_groundtruth}")
        LOGGER.info(f"  LLM annotations: {len(open(llm_text_path).read().split('------------------------')) - 1} annotations")
        LOGGER.info(f"  Groundtruth: {len(open(groundtruth_text_path).read().split('------------------------')) - 1} annotations")
        
        # Run verifier
        import subprocess
        result = subprocess.run(
            [sys.executable, str(verifier_path)],
            cwd=str(verifier_dir),
            capture_output=True,
            text=True
        )
        
        # Print results
        print("\n" + "="*80)
        print("VERIFICATION RESULTS")
        print("="*80)
        print(result.stdout)
        if result.stderr:
            print("Errors:", result.stderr)
        print("="*80)
        
        # Copy verification results back
        verification_results = verifier_dir / "verification_results.json"
        if verification_results.exists():
            shutil.copy(verification_results, output_dir / f"{legislation_id}_verification_results.json")
            LOGGER.info(f"Saved verification results to {output_dir / f'{legislation_id}_verification_results.json'}")
        
    except Exception as e:
        LOGGER.error(f"Error running verifier: {e}")
        import traceback
        traceback.print_exc()
    
    LOGGER.info(f"\nProcessing complete! All files saved to {output_dir}")
    LOGGER.info(f"  - LLM annotations: {llm_text_path}")
    LOGGER.info(f"  - Groundtruth: {groundtruth_text_path}")
    LOGGER.info(f"  - Verification results: {output_dir / f'{legislation_id}_verification_results.json'}")


def main():
    parser = argparse.ArgumentParser(
        description="Process a single section: extract, annotate, and verify"
    )
    parser.add_argument(
        "hierarchy_json",
        type=Path,
        help="Path to full hierarchy JSON file"
    )
    parser.add_argument(
        "section_id",
        help="Section ID to extract (e.g., 'section-1')"
    )
    parser.add_argument(
        "unified_csv",
        type=Path,
        help="Path to unified annotations CSV"
    )
    parser.add_argument(
        "legislation_id",
        help="Full legislation ID (e.g., '1989_41_section-1')"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/single_section"),
        help="Output directory"
    )
    parser.add_argument(
        "--model",
        default="gpt-4o-mini",
        help="Model to use"
    )
    parser.add_argument(
        "--api-key",
        help="OpenAI API key (default: OPENAI_API_KEY env var)"
    )
    
    args = parser.parse_args()
    
    process_single_section(
        hierarchy_json_path=args.hierarchy_json,
        section_id=args.section_id,
        unified_csv_path=args.unified_csv,
        legislation_id=args.legislation_id,
        output_dir=args.output_dir,
        model=args.model,
        api_key=args.api_key
    )


if __name__ == "__main__":
    main()

