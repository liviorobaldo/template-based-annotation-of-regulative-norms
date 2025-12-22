"""
Main automation pipeline that orchestrates zero-shot, few-shot, and fine-tuning methods.
Outputs results in verifier-compatible format.
"""
import argparse
import csv
import json
import logging
import os
from pathlib import Path
from typing import List, Dict, Optional

# Load environment variables early
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from zeroshot_opeai import annotate_json
from fewshot_automation import annotate_with_fewshot
from finetuning_automation import annotate_with_finetuned_model
from conersion_for_verifier import convert_annotations

LOGGER = logging.getLogger("automation_pipeline")
if not LOGGER.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def find_hierarchy_json_for_legislation(legislation_id: str, hierarchy_dir: str) -> Optional[Path]:
    """Find the hierarchy JSON file for a given legislation ID."""
    # Extract act identifier (e.g., "1989_41" from "1989_41_section-1")
    act_id = '_'.join(legislation_id.split('_')[:2])
    section_part = legislation_id.split('_', 2)[2] if len(legislation_id.split('_')) > 2 else None  # e.g., "section-1"
    
    hierarchy_path = Path(hierarchy_dir)
    
    # Collect chunk files (skip full hierarchy and outputs)
    chunk_files = []
    
    for json_file in hierarchy_path.rglob(f"*{act_id}*.json"):
        if json_file.is_file() and 'outputs' not in str(json_file):
            # Skip full hierarchy files (too large for API)
            if 'chunk' in json_file.name.lower():
                chunk_files.append(json_file)
    
    if not chunk_files:
        # Also try in the Obligation_prohibition_picking_context directories
        parent_dir = hierarchy_path.parent.parent if hierarchy_path.parent else hierarchy_path
        for act_dir in parent_dir.glob("*"):
            if act_dir.is_dir():
                for json_file in act_dir.glob(f"*{act_id}*.json"):
                    if json_file.is_file() and 'outputs' not in str(json_file):
                        if 'chunk' in json_file.name.lower():
                            chunk_files.append(json_file)
    
    if not chunk_files:
        return None
    
    # Sort chunk files by name to get consistent order
    chunk_files.sort(key=lambda x: x.name)
    
    # Try to find the chunk that likely contains this section
    # Simple heuristic: section-1 is likely in chunk_1, section-10+ might be in later chunks
    if section_part:
        try:
            # Extract section number (e.g., "1" from "section-1")
            section_num_str = section_part.replace('section-', '').split('-')[0]
            section_num = int(''.join(filter(str.isdigit, section_num_str)))
            
            # Heuristic: sections 1-20 in chunk_1, 21-40 in chunk_2, etc.
            # But we'll try chunk_1 first as it's most likely to have early sections
            if section_num <= 20:
                # Prefer chunk_1 for early sections
                for chunk_file in chunk_files:
                    if 'chunk_1' in chunk_file.name or 'chunk-1' in chunk_file.name:
                        return chunk_file
        except (ValueError, IndexError):
            pass
    
    # Default: return first chunk file
    return chunk_files[0]


def process_unified_annotations(
    unified_csv: str,
    method: str,
    output_dir: str,
    hierarchy_dir: Optional[str] = None,
    unified_csv_path: Optional[str] = None,
    model: str = "gpt-4o",
    api_key: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 4000,
    num_examples: int = 3,
    limit: Optional[int] = None
) -> Dict[str, List[Dict]]:
    """
    Process all legislation sections from unified CSV using specified method.
    
    Returns: {legislation_id: [annotations]}
    """
    results = {}
    
    with open(unified_csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    # Apply limit if specified
    if limit is not None and limit > 0:
        rows = rows[:limit]
        LOGGER.info(f"Limited to first {limit} sections")
    
    LOGGER.info(f"Processing {len(rows)} legislation sections using {method} method")
    
    for i, row in enumerate(rows, 1):
        legislation_id = row['legislation_id']
        LOGGER.info(f"[{i}/{len(rows)}] Processing {legislation_id}")
        
        # Find corresponding hierarchy JSON file
        json_path = None
        if hierarchy_dir:
            json_path = find_hierarchy_json_for_legislation(legislation_id, hierarchy_dir)
        
        if not json_path:
            LOGGER.warning(f"Could not find JSON file for {legislation_id}, skipping")
            continue
        
        try:
            # Annotate based on method
            if method == "zeroshot":
                raw_response, parsed = annotate_json(
                    json_path=json_path,
                    model=model,
                    api_key=api_key,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
            
            elif method == "fewshot":
                if not unified_csv_path:
                    unified_csv_path = unified_csv
                raw_response, parsed = annotate_with_fewshot(
                    json_path=json_path,
                    unified_csv=unified_csv_path,
                    model=model,
                    api_key=api_key,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    num_examples=num_examples,
                    legislation_id=legislation_id
                )
            
            elif method == "finetuning":
                prompt_path = Path(__file__).with_name("prompt.txt")
                raw_response, parsed = annotate_with_finetuned_model(
                    json_path=json_path,
                    model=model,
                    prompt_path=prompt_path,
                    api_key=api_key,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
            
            else:
                raise ValueError(f"Unknown method: {method}")
            
            # Store results
            if parsed:
                if isinstance(parsed, list):
                    results[legislation_id] = parsed
                elif isinstance(parsed, dict) and "annotations" in parsed:
                    results[legislation_id] = parsed["annotations"]
                else:
                    results[legislation_id] = [parsed]
            else:
                # Try to extract JSON from raw response
                LOGGER.warning(f"No parsed annotations for {legislation_id}, attempting to extract from raw response")
                try:
                    import re
                    # Try to find JSON array in the raw response
                    json_match = re.search(r'\[.*\]', raw_response, re.DOTALL)
                    if json_match:
                        try:
                            extracted_json = json.loads(json_match.group())
                            if isinstance(extracted_json, list):
                                results[legislation_id] = extracted_json
                                LOGGER.info(f"Successfully extracted {len(extracted_json)} annotations from raw response")
                            else:
                                results[legislation_id] = []
                        except json.JSONDecodeError:
                            results[legislation_id] = []
                    else:
                        results[legislation_id] = []
                except Exception as e:
                    LOGGER.error(f"Error extracting JSON from raw response: {e}")
                    results[legislation_id] = []
                
                # Save raw response for debugging
                raw_output_path = Path(output_dir) / "raw_responses" / f"{legislation_id}_raw.txt"
                raw_output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(raw_output_path, 'w', encoding='utf-8') as f:
                    f.write(raw_response)
                LOGGER.debug(f"Saved raw response to {raw_output_path}")
        
        except Exception as e:
            LOGGER.error(f"Error processing {legislation_id}: {e}")
            results[legislation_id] = []
    
    return results


def save_results(
    results: Dict[str, List[Dict]],
    output_dir: str,
    method: str,
    format: str = "both",
    per_section: bool = True
):
    """Save results in JSON and/or verifier-compatible text format.
    
    Args:
        results: Dictionary mapping legislation_id to list of annotations
        output_dir: Output directory
        method: Method name (zeroshot, fewshot, etc.)
        format: Output format (json, text, both)
        per_section: If True, save separate files per section; if False, combine all
    """
    os.makedirs(output_dir, exist_ok=True)
    
    if per_section:
        # Save per-section files
        sections_dir = Path(output_dir) / "sections"
        sections_dir.mkdir(exist_ok=True)
        
        for legislation_id, annotations in results.items():
            if not annotations:
                continue
            
            # Sanitize filename
            safe_id = legislation_id.replace('/', '_').replace('\\', '_')
            
            # Save per-section JSON
            if format in ["json", "both"]:
                section_json = sections_dir / f"{safe_id}.json"
                with open(section_json, 'w', encoding='utf-8') as f:
                    json.dump(annotations, f, ensure_ascii=False, indent=2)
            
            # Save per-section text for verifier
            if format in ["text", "both"]:
                section_text = sections_dir / f"{safe_id}.txt"
                # Create temp JSON for conversion
                temp_json = sections_dir / f"{safe_id}_temp.json"
                with open(temp_json, 'w', encoding='utf-8') as f:
                    json.dump(annotations, f, ensure_ascii=False, indent=2)
                
                convert_annotations(temp_json, output_path=section_text)
                temp_json.unlink()  # Clean up temp file
                LOGGER.info(f"Saved {legislation_id}: {len(annotations)} annotations to {section_text}")
        
        LOGGER.info(f"Saved {len([r for r in results.values() if r])} section files to {sections_dir}")
    
    # Also save combined file for reference
    all_annotations = []
    for legislation_id, annotations in results.items():
        all_annotations.extend(annotations)
    
    json_path = None
    
    # Save combined JSON
    if format in ["json", "both"]:
        json_path = Path(output_dir) / f"{method}_annotations_combined.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(all_annotations, f, ensure_ascii=False, indent=2)
        LOGGER.info(f"Saved combined JSON to {json_path}")
    
    # Save combined verifier-compatible text
    if format in ["text", "both"]:
        text_path = Path(output_dir) / f"{method}_annotations_combined.txt"
        if json_path is None:
            json_path = Path(output_dir) / f"{method}_annotations_temp.json"
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(all_annotations, f, ensure_ascii=False, indent=2)
        
        convert_annotations(json_path, output_path=text_path)
        LOGGER.info(f"Saved combined text to {text_path}")
        
        if format == "text" and json_path.name.endswith("_temp.json"):
            json_path.unlink()
    
    # Save breakdown
    breakdown_path = Path(output_dir) / f"{method}_breakdown.json"
    with open(breakdown_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    LOGGER.info(f"Saved breakdown to {breakdown_path}")


def run_pipeline(
    unified_csv: str,
    method: str,
    output_dir: str,
    hierarchy_dir: Optional[str] = None,
    model: str = "gpt-4o",
    api_key: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 4000,
    num_examples: int = 3,
    format: str = "both",
    limit: Optional[int] = None,
    per_section: bool = True
):
    """Run the complete automation pipeline."""
    LOGGER.info(f"Starting {method} automation pipeline")
    LOGGER.info(f"Input: {unified_csv}")
    LOGGER.info(f"Output: {output_dir}")
    LOGGER.info(f"Per-section output: {per_section}")
    
    # Process all legislation sections
    results = process_unified_annotations(
        unified_csv=unified_csv,
        method=method,
        output_dir=output_dir,
        hierarchy_dir=hierarchy_dir,
        unified_csv_path=unified_csv,
        model=model,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        num_examples=num_examples,
        limit=limit
    )
    
    # Save results
    save_results(results, output_dir, method, format, per_section=per_section)
    
    # Print summary
    total_annotations = sum(len(anns) for anns in results.values())
    LOGGER.info(f"\nPipeline complete!")
    LOGGER.info(f"Processed {len(results)} legislation sections")
    LOGGER.info(f"Generated {total_annotations} total annotations")
    LOGGER.info(f"Results saved to {output_dir}")
    if per_section:
        LOGGER.info(f"Per-section files saved to {output_dir}/sections/")


def run_cli(argv: Optional[List[str]] = None) -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Automation pipeline for legal annotation (zero-shot, few-shot, fine-tuning)"
    )
    parser.add_argument(
        "unified_csv",
        type=Path,
        help="Path to unified annotations CSV (from aggregate_all_annotations.py)"
    )
    parser.add_argument(
        "method",
        choices=["zeroshot", "fewshot", "finetuning"],
        help="Annotation method to use"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default="output",
        help="Output directory for results"
    )
    parser.add_argument(
        "--hierarchy-dir",
        type=Path,
        help="Directory containing hierarchy JSON files (searches recursively)"
    )
    parser.add_argument(
        "--model",
        default="gpt-4o",
        help="Model to use (for zeroshot/fewshot) or fine-tuned model name (for finetuning)"
    )
    parser.add_argument(
        "--api-key",
        help="OpenAI API key (default: OPENAI_API_KEY env var)"
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.2,
        help="Sampling temperature"
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=4000,
        help="Maximum tokens in response"
    )
    parser.add_argument(
        "--num-examples",
        type=int,
        default=3,
        help="Number of examples for few-shot method"
    )
    parser.add_argument(
        "--format",
        choices=["json", "text", "both"],
        default="both",
        help="Output format"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit processing to first N sections (for testing)"
    )
    parser.add_argument(
        "--per-section",
        action="store_true",
        default=True,
        help="Save separate files per section (default: True)"
    )
    parser.add_argument(
        "--no-per-section",
        dest="per_section",
        action="store_false",
        help="Combine all sections into single files"
    )
    
    args = parser.parse_args(args=argv)
    
    run_pipeline(
        unified_csv=str(args.unified_csv),
        method=args.method,
        output_dir=str(args.output_dir),
        hierarchy_dir=str(args.hierarchy_dir) if args.hierarchy_dir else None,
        model=args.model,
        api_key=args.api_key,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        num_examples=args.num_examples,
        format=args.format,
        limit=args.limit,
        per_section=args.per_section
    )


if __name__ == "__main__":
    run_cli()

