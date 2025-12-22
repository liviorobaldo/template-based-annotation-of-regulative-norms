"""
Aggregate verification results from all experiments.
Combines results from all sections and models into summary statistics.
"""
import json
from pathlib import Path
from collections import defaultdict


def aggregate_verification_results(results_dir: Path):
    """Aggregate all verification results from experiments."""
    results_dir = Path(results_dir)
    
    if not results_dir.exists():
        print(f"Results directory not found: {results_dir}")
        return
    
    # Structure: {model: {section: results}}
    all_results = defaultdict(dict)
    
    # Collect all verification results
    # Structure: results/{model}/{section_id}/{section_id}_verification_results.json
    for model_dir in results_dir.iterdir():
        if not model_dir.is_dir():
            continue
        
        model_name = model_dir.name
        print(f"Processing model: {model_name}")
        
        for section_dir in model_dir.iterdir():
            if not section_dir.is_dir():
                continue
            
            section_id = section_dir.name
            verification_file = section_dir / f"{section_id}_verification_results.json"
            
            if verification_file.exists():
                try:
                    with open(verification_file, 'r', encoding='utf-8') as f:
                        results = json.load(f)
                    all_results[model_name][section_id] = results
                    print(f"  ✓ Loaded {section_id}")
                except Exception as e:
                    print(f"  ✗ Error loading {section_id}: {e}")
            else:
                print(f"  ⚠ Verification file not found: {verification_file}")
    
    # Calculate aggregate statistics
    aggregate_stats = {}
    
    for model_name, sections in all_results.items():
        # First, collect all section stats
        section_stats_dict = {}
        totals = {
            'exactly_identical': 0,
            'reasonably_equal': 0,
            'same_meaning_substantial_paraphrase': 0,
            'same_norm_different_meaning': 0,
            'only_in_annotations': 0,
            'only_in_groundtruth': 0
        }
        
        for section_id, results in sections.items():
            section_stats = {
                'exactly_identical': len(results.get('exactly_identical', [])),
                'reasonably_equal': len(results.get('reasonably_equal', [])),
                'same_meaning_substantial_paraphrase': len(results.get('same_meaning_substantial_paraphrase', [])),
                'same_norm_different_meaning': len(results.get('same_norm_different_meaning', [])),
                'only_in_annotations': len(results.get('only_in_annotations', [])),
                'only_in_groundtruth': len(results.get('only_in_groundtruth', []))
            }
            
            # Add to totals
            totals['exactly_identical'] += section_stats['exactly_identical']
            totals['reasonably_equal'] += section_stats['reasonably_equal']
            totals['same_meaning_substantial_paraphrase'] += section_stats['same_meaning_substantial_paraphrase']
            totals['same_norm_different_meaning'] += section_stats['same_norm_different_meaning']
            totals['only_in_annotations'] += section_stats['only_in_annotations']
            totals['only_in_groundtruth'] += section_stats['only_in_groundtruth']
            
            section_stats_dict[section_id] = section_stats
        
        # Calculate totals
        # Total matched pairs (categories 1-4)
        total_matched = (totals['exactly_identical'] + 
                        totals['reasonably_equal'] + 
                        totals['same_meaning_substantial_paraphrase'] + 
                        totals['same_norm_different_meaning'])
        
        # Total annotations (matched + only_in_annotations)
        total_annotations = total_matched + totals['only_in_annotations']
        
        # Total groundtruth (matched + only_in_groundtruth)
        total_groundtruth = total_matched + totals['only_in_groundtruth']
        
        # Use a unified total for all percentages: total_annotations + total_groundtruth
        # This represents all items (matched appear in both, unmatched appear once)
        unified_total = total_annotations + total_groundtruth
        
        # Calculate percentages relative to unified total (avoid division by zero)
        if unified_total > 0:
            exactly_identical_pct = f"{round((totals['exactly_identical'] / unified_total) * 100, 2)}%"
            reasonably_equal_pct = f"{round((totals['reasonably_equal'] / unified_total) * 100, 2)}%"
            same_meaning_pct = f"{round((totals['same_meaning_substantial_paraphrase'] / unified_total) * 100, 2)}%"
            same_norm_pct = f"{round((totals['same_norm_different_meaning'] / unified_total) * 100, 2)}%"
            only_in_annotations_pct = f"{round((totals['only_in_annotations'] / unified_total) * 100, 2)}%"
            only_in_groundtruth_pct = f"{round((totals['only_in_groundtruth'] / unified_total) * 100, 2)}%"
        else:
            exactly_identical_pct = "0.0%"
            reasonably_equal_pct = "0.0%"
            same_meaning_pct = "0.0%"
            same_norm_pct = "0.0%"
            only_in_annotations_pct = "0.0%"
            only_in_groundtruth_pct = "0.0%"
        
        # Build stats dictionary with percentages right after counts
        stats = {
            'total_sections': len(sections),
            'exactly_identical': totals['exactly_identical'],
            'exactly_identical_pct': exactly_identical_pct,
            'reasonably_equal': totals['reasonably_equal'],
            'reasonably_equal_pct': reasonably_equal_pct,
            'same_meaning_substantial_paraphrase': totals['same_meaning_substantial_paraphrase'],
            'same_meaning_substantial_paraphrase_pct': same_meaning_pct,
            'same_norm_different_meaning': totals['same_norm_different_meaning'],
            'same_norm_different_meaning_pct': same_norm_pct,
            'only_in_annotations': totals['only_in_annotations'],
            'only_in_annotations_pct': only_in_annotations_pct,
            'only_in_groundtruth': totals['only_in_groundtruth'],
            'only_in_groundtruth_pct': only_in_groundtruth_pct,
            'total_matched': total_matched,
            'total_annotations': total_annotations,
            'total_groundtruth': total_groundtruth,
            'unified_total': unified_total,
            'sections': section_stats_dict
        }
        
        aggregate_stats[model_name] = stats
    
    # Save aggregated results
    output_file = results_dir / "aggregated_results.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(aggregate_stats, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*80}")
    print("AGGREGATED RESULTS")
    print(f"{'='*80}\n")
    
    # Print summary
    for model_name, stats in aggregate_stats.items():
        print(f"Model: {model_name}")
        print(f"  Total sections: {stats['total_sections']}")
        print(f"  Exactly identical: {stats['exactly_identical']} ({stats['exactly_identical_pct']})")
        print(f"  Reasonably equal: {stats['reasonably_equal']} ({stats['reasonably_equal_pct']})")
        print(f"  Same meaning (substantial paraphrase): {stats['same_meaning_substantial_paraphrase']} ({stats['same_meaning_substantial_paraphrase_pct']})")
        print(f"  Same norm, different meaning: {stats['same_norm_different_meaning']} ({stats['same_norm_different_meaning_pct']})")
        print(f"  Only in LLM annotations: {stats['only_in_annotations']} ({stats['only_in_annotations_pct']})")
        print(f"  Only in groundtruth: {stats['only_in_groundtruth']} ({stats['only_in_groundtruth_pct']})")
        print(f"  Total matched pairs: {stats['total_matched']}")
        print(f"  Total LLM annotations: {stats['total_annotations']}")
        print(f"  Total groundtruth: {stats['total_groundtruth']}")
        print()
    
    print(f"Detailed results saved to: {output_file}")
    print(f"{'='*80}")
    
    return aggregate_stats


if __name__ == "__main__":
    import sys
    base_dir = Path(__file__).parent
    results_dir = base_dir / "results"
    
    if len(sys.argv) > 1:
        results_dir = Path(sys.argv[1])
    
    aggregate_verification_results(results_dir)