"""
This script is used to verify the annotations of the deontic sentences.
We will be doing this:
(1) Count and list the annotations whose text is exactly identical in both sets, 
    ignoring minor differences such as spacing, capitalization, or punctuation.
(2) Count and list the annotations that can be considered reasonably equal in both sets; 
    "reasonably equal" means that the two annotations convey the same meaning and have 
    nearly identical text, differing only in minor paraphrasing.
(3) Count and list the annotations that convey the same meaning but differ substantially 
    in text (i.e., one is a significant paraphrase of the other).
(4) Count and list the annotations that appear to annotate the same norm but convey 
    a different meaning.
(5) Count and list annotations that appear only in the first set with no counterpart 
    in the second set.
(6) Count and list annotations that appear only in the second set with no counterpart 
    in the first set.
"""

import re
import json
import os
from typing import List, Tuple, Dict, Set
from collections import defaultdict
from rapidfuzz import fuzz, process
from dotenv import load_dotenv
from openai import OpenAI
from datetime import datetime


def normalize_text(text: str) -> str:
    """Normalize text by removing extra whitespace, converting to lowercase."""
    # Remove multiple spaces and newlines, convert to lowercase
    text = re.sub(r'\s+', ' ', text)
    text = text.strip().lower()
    return text


def parse_annotations(file_path: str) -> List[str]:
    """
    Parse annotation file and extract individual annotations.
    Annotations are separated by a line containing only dashes.
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Split by separator lines (lines containing only dashes)
    annotations = re.split(r'^-+$', content, flags=re.MULTILINE)
    
    # Clean up each annotation
    parsed_annotations = []
    for ann in annotations:
        ann = ann.strip()
        if ann:  # Skip empty strings
            parsed_annotations.append(ann)
    
    return parsed_annotations


def similarity_score(text1: str, text2: str) -> float:
    """Deprecated: retained for compatibility; not used in LLM-only flow."""
    normalized1 = normalize_text(text1)
    normalized2 = normalize_text(text2)
    return fuzz.ratio(normalized1, normalized2) / 100.0


def match_annotations(annotations1: List[str], annotations2: List[str], 
                     threshold: float = 0.6) -> Dict[int, int]:
    """
    Match annotations between two sets using similarity scores.
    Returns a dictionary mapping indices from annotations1 to indices in annotations2.
    Uses rapidfuzz.process.extract for efficient matching.
    Handles duplicates by finding the best available (unused) match.
    """
    matches = {}
    used_indices2 = set()
    
    # Use rapidfuzz process.extract to find multiple potential matches
    # process.extract returns [(matched_text, score, index), ...] sorted by score
    for i, ann1 in enumerate(annotations1):
        # Get multiple potential matches, sorted by score (best first)
        # We get more than one to handle duplicates - if the best match is already used,
        # we can use the next best match
        potential_matches = process.extract(
            ann1, 
            annotations2, 
            scorer=fuzz.token_sort_ratio,
            limit=len(annotations2),  # Get all matches above threshold
            score_cutoff=int(threshold * 100)  # Convert to 0-100 range
        )
        
        # Find the first match that hasn't been used yet
        for matched_text, score, j in potential_matches:
            if j not in used_indices2:
                matches[i] = j
                used_indices2.add(j)
                break  # Found a match, move to next annotation
    
    return matches


def classify_relationship(ann1: str, ann2: str) -> int:
    """Deprecated: LLM is used for categorization now."""
    return 4


CATEGORY_ID_TO_NAME = {
    1: "exactly_identical",
    2: "reasonably_equal",
    3: "same_meaning_substantial_paraphrase",
    4: "same_norm_different_meaning",
    5: "only_in_annotations",
    6: "only_in_groundtruth",
}


def _batch(iterable: List[dict], size: int) -> List[List[dict]]:
    batched = []
    current = []
    for item in iterable:
        current.append(item)
        if len(current) == size:
            batched.append(current)
            current = []
    if current:
        batched.append(current)
    return batched


def compute_llm_category_for_pairs(pairs: List[Dict], model: str = "gpt-4o-mini") -> Dict[str, str]:
    """
    Ask OpenAI to classify each pair into one of categories 1, 2, 3, or 4:
    - 1: exactly_identical (ignore spacing/case/punctuation)
    - 2: reasonably_equal
    - 3: same_meaning_substantial_paraphrase
    - 4: same_norm_different_meaning

    Returns mapping {pair_id: category_key_string} where category_key_string is one of
    CATEGORY_ID_TO_NAME[1], CATEGORY_ID_TO_NAME[2], CATEGORY_ID_TO_NAME[3], CATEGORY_ID_TO_NAME[4].
    """
    # Load environment
    load_dotenv()

    client = OpenAI()

    results: Dict[str, str] = {}
    for group in _batch(pairs, 5):
        # Build a JSON-friendly payload for the model
        payload = [
            {
                "pair_id": p["pair_id"],
                "annotation": p["annotation"],
                "groundtruth": p["groundtruth"],
            }
            for p in group
        ]

        system_prompt = (
            "You are a careful adjudicator of semantic relationship between two short policy/annotation texts. "
            "For each pair, choose EXACTLY ONE of these categories and respond ONLY with JSON: "
            "'exactly_identical' (ignoring spacing/case/punctuation), "
            "'reasonably_equal' (same meaning, nearly identical text), "
            "'same_meaning_substantial_paraphrase' (same meaning, substantial paraphrase), "
            "'same_norm_different_meaning' (appear to annotate the same norm but meaning differs)."
        )

        user_prompt = (
            "Classify the following pairs. Respond ONLY with a JSON object of shape {\"results\":[{\"pair_id\":..., \"category\": one of the four strings}]}.\n\n" +
            json.dumps({"pairs": payload}, ensure_ascii=False)
        )

        # Log request
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            req_log_path = os.path.join(base_dir, "openai_requests.jsonl")
            req_entry = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "model": model,
                "system_prompt": system_prompt,
                "user_payload": payload,
            }
            with open(req_log_path, 'a', encoding='utf-8') as lf:
                lf.write(json.dumps(req_entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

        completion = client.chat.completions.create(
            model=model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        content = completion.choices[0].message.content
        # Log response
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            res_log_path = os.path.join(base_dir, "openai_responses.jsonl")
            res_entry = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "model": model,
                "response": content,
            }
            with open(res_log_path, 'a', encoding='utf-8') as lf:
                lf.write(json.dumps(res_entry, ensure_ascii=False) + "\n")
        except Exception:
            pass
        try:
            parsed = json.loads(content)
            for item in parsed.get("results", []):
                pid = item.get("pair_id")
                cat = item.get("category")
                if (
                    isinstance(pid, str)
                    and isinstance(cat, str)
                    and cat in {
                        CATEGORY_ID_TO_NAME[1],
                        CATEGORY_ID_TO_NAME[2],
                        CATEGORY_ID_TO_NAME[3],
                        CATEGORY_ID_TO_NAME[4],
                    }
                ):
                    results[pid] = cat
        except Exception:
            # If parsing fails, skip this batch silently to avoid breaking the whole run
            continue

    return results


def verify_annotations(annotations_file: str, groundtruth_file: str) -> Dict:
    """
    Main verification function.
    Takes two txt files with annotations and returns detailed results.
    """
    # Parse both files
    annotations = parse_annotations(annotations_file)
    groundtruth = parse_annotations(groundtruth_file)
    
    print(f"Parsed {len(annotations)} annotations from {annotations_file}")
    print(f"Parsed {len(groundtruth)} annotations from {groundtruth_file}")
    print()
    
    # Match annotations
    matches = match_annotations(annotations, groundtruth)
    
    # Categorize matched pairs using LLM only
    # Prepare pairs for LLM
    pairs = []
    for idx1, idx2 in matches.items():
        pairs.append({
            'pair_id': f"{idx1}-{idx2}",
            'annotation': annotations[idx1],
            'groundtruth': groundtruth[idx2],
        })

    llm_decisions = compute_llm_category_for_pairs(pairs)

    # Initialize results with named categories
    results = {
        CATEGORY_ID_TO_NAME[1]: [],
        CATEGORY_ID_TO_NAME[2]: [],
        CATEGORY_ID_TO_NAME[3]: [],
        CATEGORY_ID_TO_NAME[4]: [],
        CATEGORY_ID_TO_NAME[5]: [],
        CATEGORY_ID_TO_NAME[6]: [],
    }

    # Process matched pairs based on LLM decisions
    matched_indices1 = set(matches.keys())
    matched_indices2 = set(matches.values())

    for idx1, idx2 in matches.items():
        ann1 = annotations[idx1]
        ann2 = groundtruth[idx2]
        pid = f"{idx1}-{idx2}"
        decided_category = llm_decisions.get(pid, CATEGORY_ID_TO_NAME[4])
        results[decided_category].append({
            'pair_id': pid,
            'annotation': ann1,
            'groundtruth': ann2,
            'annotation_index': idx1,
            'groundtruth_index': idx2,
            'llm_category': decided_category,
        })
    
    # Category 5: Only in annotations
    for i, ann in enumerate(annotations):
        if i not in matched_indices1:
            results[CATEGORY_ID_TO_NAME[5]].append({
                'annotation': ann,
                'annotation_index': i
            })
    
    # Category 6: Only in groundtruth
    for i, ann in enumerate(groundtruth):
        if i not in matched_indices2:
            results[CATEGORY_ID_TO_NAME[6]].append({
                'groundtruth': ann,
                'groundtruth_index': i
            })
    
    # Print summary
    print("=" * 80)
    print("VERIFICATION RESULTS")
    print("=" * 80)
    print(f"Exactly identical: {len(results[CATEGORY_ID_TO_NAME[1]])}")
    print(f"Reasonably equal: {len(results[CATEGORY_ID_TO_NAME[2]])}")
    print(f"Same meaning, substantial paraphrase: {len(results[CATEGORY_ID_TO_NAME[3]])}")
    print(f"Same norm, different meaning: {len(results[CATEGORY_ID_TO_NAME[4]])}")
    print(f"Only in annotations: {len(results[CATEGORY_ID_TO_NAME[5]])}")
    print(f"Only in groundtruth: {len(results[CATEGORY_ID_TO_NAME[6]])}")
    print("=" * 80)
    print()
    
    return results


def save_results(results: Dict, output_file: str):
    """Save detailed results to a JSON file."""
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"Detailed results saved to {output_file}")


def print_detailed_results(results: Dict, category_key: str, max_display: int = 5):
    """Print detailed results for a specific category (by name key)."""
    if not results.get(category_key, []):
        print(f"\nNo results for category {category_key}")
        return
    
    print(f"\n{'=' * 80}")
    print(f"CATEGORY {category_key}: {len(results[category_key])} items")
    print(f"{'=' * 80}")
    
    for i, item in enumerate(results[category_key][:max_display]):
        print(f"\nItem {i+1}:")
        if 'annotation' in item:
            print(f"Annotation [{item['annotation_index']}] (first {200} chars):")
            print(item['annotation'][:200] + "..." if len(item['annotation']) > 200 else item['annotation'])
        if 'groundtruth' in item:
            print(f"Groundtruth [{item['groundtruth_index']}] (first {200} chars):")
            print(item['groundtruth'][:200] + "..." if len(item['groundtruth']) > 200 else item['groundtruth'])
    
    if len(results[category_key]) > max_display:
        print(f"\n... and {len(results[category_key]) - max_display} more items")


def enrich_with_llm_decisions(results: Dict) -> None:
    """
    For categories 2, 3, and 4, ask LLM to choose the most appropriate category
    and reassign items accordingly. Stores chosen category in 'llm_category'.
    """
    target_keys = [
        CATEGORY_ID_TO_NAME[2],
        CATEGORY_ID_TO_NAME[3],
        CATEGORY_ID_TO_NAME[4],
    ]

    pairs: List[Dict] = []
    index_map: Dict[str, Tuple[str, int]] = {}
    # Build list of pairs and a map to write back results
    for key in target_keys:
        for idx, item in enumerate(results.get(key, [])):
            pair_id = item.get('pair_id') or f"{item.get('annotation_index')}-{item.get('groundtruth_index')}"
            pairs.append({
                'pair_id': pair_id,
                'annotation': item.get('annotation', ''),
                'groundtruth': item.get('groundtruth', ''),
            })
            index_map[pair_id] = (key, idx)

    if not pairs:
        return

    llm_categories = compute_llm_category_for_pairs(pairs)

    # Re-bucket items according to LLM decisions
    for key in target_keys:
        items = results.get(key, [])
        if not items:
            continue
        new_items = []
        for item in items:
            pid = item.get('pair_id') or f"{item.get('annotation_index')}-{item.get('groundtruth_index')}"
            decided = llm_categories.get(pid)
            if decided and decided in results and decided != key:
                moved_item = dict(item)
                moved_item['llm_category'] = decided
                results[decided].append(moved_item)
            else:
                if decided:
                    item['llm_category'] = decided
                new_items.append(item)
        results[key] = new_items


if __name__ == "__main__":
    # Get the directory where this script is located
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # File paths relative to the script directory
    annotations_file = os.path.join(base_dir, "annotation.txt")
    groundtruth_file = os.path.join(base_dir, "groundtruth1.txt")
    output_file = os.path.join(base_dir, "verification_results.json")
    
    # Run verification
    results = verify_annotations(annotations_file, groundtruth_file)
    
    # Save results to JSON
    save_results(results, output_file)
    
    # Print detailed results for each category (by name)
    for category_key in [
        CATEGORY_ID_TO_NAME[1],
        CATEGORY_ID_TO_NAME[2],
        CATEGORY_ID_TO_NAME[3],
        CATEGORY_ID_TO_NAME[4],
        CATEGORY_ID_TO_NAME[5],
        CATEGORY_ID_TO_NAME[6],
    ]:
        print_detailed_results(results, category_key, max_display=3)
