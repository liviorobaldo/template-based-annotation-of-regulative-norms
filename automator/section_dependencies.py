"""
Section Dependency Analyzer

This module analyzes annotations to identify cross-section dependencies.
A dependency exists when an annotation's condition references a different section
than its main_section.

Usage:
    from automator.section_dependencies import build_dependency_map, get_dependent_sections
    
    # Build dependency map from unified CSV
    deps = build_dependency_map('automator/data/unified_annotations.csv')
    
    # Get dependent sections for a specific legislation_id
    dependent_sections = get_dependent_sections('2010_15_section-29', deps)
"""
import csv
import json
import re
from pathlib import Path
from collections import defaultdict
from typing import Dict, Set, List


def build_dependency_map(unified_csv_path: Path) -> Dict[str, Dict[str, Set[str]]]:
    """
    Build a dependency map from unified_annotations.csv.
    
    Returns:
        {act_id: {main_section: {referenced_sections}}}
        Example: {'2010_15': {'29': {'28'}, '33': {'32'}}}
    """
    dependency_map = defaultdict(lambda: defaultdict(set))
    
    with open(unified_csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            legislation_id = row['legislation_id']
            annotations_json = row['annotations']
            
            try:
                annotations = json.loads(annotations_json)
            except json.JSONDecodeError:
                continue
            
            # Parse legislation_id: 2010_15_section-29 -> act_id='2010_15', section='29'
            parts = legislation_id.split('_')
            if len(parts) < 3:
                continue
            
            act_id = f'{parts[0]}_{parts[1]}'
            main_section = '_'.join(parts[2:]).replace('section-', '')
            
            # Check all annotations for this section
            for annotation in annotations:
                if not isinstance(annotation, dict):
                    continue
                
                # Get referenced sections from conditions
                for cond in annotation.get('conditions', []):
                    cond_section_url = cond.get('section', '')
                    if not cond_section_url:
                        continue
                    
                    # Extract section number from URL
                    match = re.search(r'/ukpga/(\d+)/(\d+)/section/(\d+[A-Z]*)', cond_section_url)
                    if match:
                        cond_year, cond_chapter, cond_sec = match.groups()
                        cond_act_id = f'{cond_year}_{cond_chapter}'
                        
                        # Only same act and different section
                        if cond_act_id == act_id and cond_sec != main_section:
                            dependency_map[act_id][main_section].add(cond_sec)
    
    # Convert defaultdict to regular dict for return
    return {act_id: {sec: set(refs) for sec, refs in deps.items()} 
            for act_id, deps in dependency_map.items()}


def get_dependent_sections(legislation_id: str, dependency_map: Dict[str, Dict[str, Set[str]]]) -> List[str]:
    """
    Get list of dependent section IDs for a given legislation_id.
    
    Args:
        legislation_id: Format like '2010_15_section-29'
        dependency_map: Dependency map from build_dependency_map()
    
    Returns:
        List of legislation_ids that this section depends on
        Example: ['2010_15_section-28']
    """
    # Parse legislation_id: 2010_15_section-29 -> act_id='2010_15', section='29'
    parts = legislation_id.split('_')
    if len(parts) < 3:
        return []
    
    act_id = f'{parts[0]}_{parts[1]}'
    section_id = '_'.join(parts[2:]).replace('section-', '')
    
    # Get dependencies for this section
    if act_id in dependency_map and section_id in dependency_map[act_id]:
        dependent_sections = dependency_map[act_id][section_id]
        # Convert to legislation_id format
        return [f'{act_id}_section-{ref_sec}' for ref_sec in dependent_sections]
    
    return []


def get_dependency_summary(dependency_map: Dict[str, Dict[str, Set[str]]]) -> Dict:
    """
    Get summary statistics about dependencies.
    
    Returns:
        Dict with summary statistics
    """
    total_acts = len(dependency_map)
    total_sections_with_deps = sum(len(deps) for deps in dependency_map.values())
    total_dependencies = sum(len(refs) for deps in dependency_map.values() for refs in deps.values())
    
    # Find most common dependency patterns
    dependency_counts = defaultdict(int)
    for act_deps in dependency_map.values():
        for main_sec, refs in act_deps.items():
            for ref_sec in refs:
                dependency_counts[f'{main_sec}->{ref_sec}'] += 1
    
    return {
        'total_acts_with_dependencies': total_acts,
        'total_sections_with_dependencies': total_sections_with_deps,
        'total_cross_section_references': total_dependencies,
        'most_common_patterns': dict(sorted(dependency_counts.items(), key=lambda x: x[1], reverse=True)[:10])
    }


if __name__ == "__main__":
    # Test the dependency analyzer
    unified_csv = Path(__file__).parent / "data" / "unified_annotations.csv"
    
    if unified_csv.exists():
        print("Building dependency map from unified_annotations.csv...")
        deps = build_dependency_map(unified_csv)
        
        print("\n" + "="*80)
        print("DEPENDENCY MAP")
        print("="*80)
        for act_id, act_deps in sorted(deps.items()):
            print(f"\nAct {act_id}:")
            for main_sec, refs in sorted(act_deps.items()):
                print(f"  Section {main_sec} -> {sorted(refs)}")
        
        print("\n" + "="*80)
        print("SUMMARY")
        print("="*80)
        summary = get_dependency_summary(deps)
        for key, value in summary.items():
            print(f"  {key}: {value}")
        
        # Test get_dependent_sections
        print("\n" + "="*80)
        print("TEST: Get dependent sections")
        print("="*80)
        test_cases = ['2010_15_section-29', '2010_15_section-33', '1989_41_section-80']
        for test_id in test_cases:
            dependent = get_dependent_sections(test_id, deps)
            print(f"  {test_id} -> {dependent}")
    else:
        print(f"Unified CSV not found: {unified_csv}")

