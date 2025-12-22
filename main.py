"""
Main file to run the experiments for the paper.
Assumes all files are in their respective folders.
Results will be in result folder.

Each experiment runs section by section.
For each experiment in the result folder there will be files for each section:
- groundtruth (from unified CSV)
- LLM generation (from zero-shot)
- verifier results (comparison)
"""
import csv
import sys
from pathlib import Path

# Add automator to path
sys.path.insert(0, str(Path(__file__).parent / "automator"))

from automator.process_single_section import process_single_section


def get_sections_from_unified_csv(unified_csv_path: Path, limit: int = 10):
    """Get first N sections from unified CSV."""
    sections = []
    with open(unified_csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if i >= limit:
                break
            legislation_id = row['legislation_id']
            # Extract section ID (e.g., "section-1" from "1989_41_section-1")
            # Format: {year}_{chapter}_{section-id}
            parts = legislation_id.split('_')
            if len(parts) >= 3:
                section_id = '_'.join(parts[2:])  # Join all parts after year_chapter
                sections.append({
                    'legislation_id': legislation_id,
                    'section_id': section_id
                })
            else:
                print(f"Warning: Could not parse legislation_id: {legislation_id}")
    return sections


def run_experiments(method: str = "zeroshot"):
    """
    Run experiments for multiple sections and models.
    
    Args:
        method: "zeroshot" or "fewshot"
    """
    # Paths
    base_dir = Path(__file__).parent
    sections_csv_dir = base_dir / "Obligation_prohibition_picking_context"  # Directory containing act_sections.csv files
    unified_csv = base_dir / "automator" / "data" / "unified_annotations.csv"
    results_dir = base_dir / "results"
    
    # Models to test
    base_models = ["gpt-4o-mini", "gpt-4o"]
    
    # Get first 10 sections
    sections = get_sections_from_unified_csv(unified_csv, limit=10)
    
    method_label = "few-shot" if method == "fewshot" else "zero-shot"
    print(f"Running {method_label} experiments for {len(sections)} sections")
    print(f"Models: {', '.join(base_models)}")
    print(f"Results will be saved to: {results_dir}\n")
    
    # Run for each model
    for base_model in base_models:
        # Create model name with method suffix for few-shot
        if method == "fewshot":
            model_name = f"{base_model}-fewshot"
        else:
            model_name = base_model
        
        print(f"\n{'='*80}")
        print(f"Running {method_label} experiments with model: {model_name} ({base_model})")
        print(f"{'='*80}\n")
        
        model_results_dir = results_dir / model_name
        
        # Run for each section
        for i, section_info in enumerate(sections, 1):
            legislation_id = section_info['legislation_id']
            section_id = section_info['section_id']
            
            print(f"[{i}/{len(sections)}] Processing {legislation_id} (section {section_id})")
            
            section_output_dir = model_results_dir / legislation_id
            
            try:
                process_single_section(
                    section_id=section_id,
                    unified_csv_path=unified_csv,
                    legislation_id=legislation_id,
                    output_dir=section_output_dir,
                    model=base_model,  # Use base model name for API
                    api_key=None,  # Will use env var
                    sections_csv_dir=sections_csv_dir,  # Directory containing act_sections.csv files
                    method=method  # Pass method parameter
                )
                print(f"✓ Completed {legislation_id}\n")
            except Exception as e:
                print(f"✗ Error processing {legislation_id}: {e}\n")
                import traceback
                traceback.print_exc()
                continue
    
    print(f"\n{'='*80}")
    print("All experiments completed!")
    print(f"Results saved to: {results_dir}")
    print(f"{'='*80}")


if __name__ == "__main__":
    import sys
    
    # Check if fewshot argument is provided
    if len(sys.argv) > 1 and sys.argv[1] == "fewshot":
        run_experiments(method="fewshot")
    else:
        # Default: run zero-shot
        run_experiments(method="fewshot")