import os
import json
import re

def main():
    # Get all input JSON files in outputs/
    in_dir = "input_for_reference_assigner"
    out_dir = "outputs_for_reference_assigner/regex"
    os.makedirs(out_dir, exist_ok=True)
    all_json_files = [f for f in os.listdir(in_dir) if f.endswith("_sections_hierarchy.json")]
    for file in all_json_files[0:1]:
        in_path = os.path.join(in_dir, file)
        print(f"Processing {in_path}")
        process_json_and_save_with_refs_regex(in_path, out_dir)

def following_regex(text, section_title=None):
    """
    Extract section references using regex patterns instead of LLM.
    This function uses multiple regex patterns to identify references to sections in legal text.
    
    Key principles:
    - "section X" refers to another section (same or different act)
    - "subsection (X)" alone typically refers to subsection within same section (NOT extracted)
    - "subsection (X) of that section" or "subsection (X) of section Y" refers to subsection X within section Y
    - Only extract actual section references, not subsection references within the same section
    
    Returns a list of dictionaries with 'section_number' and 'act' keys.
    """
    if not text or not isinstance(text, str):
        return []
    
    references = []
    text_lower = text.lower()
    
    # Pattern 1: Explicit section reference with act name
    # Matches: "section 73 of the Civil Partnership Act 2004"
    # Matches: "section 3 of that Act"
    # Matches: "section 63(1) of the Family Law Act 1996"
    pattern1 = re.compile(
        r'section\s+(\d+[A-Z]?)(?:\([^)]+\))?\s+of\s+(?:the\s+)?(?:([A-Z][^;.,]+(?:Act|Law|Order|Regulation)\s+\d{4})|that\s+Act|this\s+Act)',
        re.IGNORECASE
    )
    for match in pattern1.finditer(text):
        section_num = match.group(1).strip()
        act_name = match.group(2).strip() if match.group(2) else "same act"
        # Clean up act name
        act_name = re.sub(r'\s+', ' ', act_name).strip()
        if act_name.lower() in ['that act', 'this act']:
            act_name = "same act"
        references.append({
            'section_number': section_num if not section_num.isdigit() else int(section_num),
            'act': act_name
        })
    
    # Pattern 2: Section reference followed by act name (act name comes after section mention)
    # Matches: "section 98 of the Adoption and Children Act 2002"
    pattern2 = re.compile(
        r'section\s+(\d+[A-Z]?)(?:\([^)]+\))?\s+(?:in|under|of|from)\s+(?:the\s+)?([A-Z][^;.,]+(?:Act|Law|Order|Regulation)\s+\d{4})',
        re.IGNORECASE
    )
    for match in pattern2.finditer(text):
        section_num = match.group(1).strip()
        act_name = match.group(2).strip()
        act_name = re.sub(r'\s+', ' ', act_name).strip()
        # Check if we already captured this in pattern1
        if not any(ref['section_number'] == (section_num if not section_num.isdigit() else int(section_num)) 
                   and ref.get('act', '').lower() == act_name.lower() 
                   for ref in references):
            references.append({
                'section_number': section_num if not section_num.isdigit() else int(section_num),
                'act': act_name
            })
    
    # Pattern 3: Multiple sections (section X or Y, section X, Y and Z, sections X and Y)
    # Matches: "section 17 or 18"
    # Matches: "section 2, 3 and 4"
    # Matches: "sections 31A and 31B"
    pattern3 = re.compile(
        r'sections?\s+(\d+[A-Z]?)(?:\s*(?:[,]|or|and)\s*(\d+[A-Z]?))+(?:\s+of\s+(?:the\s+)?([A-Z][^;.,]+(?:Act|Law|Order|Regulation)\s+\d{4}))?',
        re.IGNORECASE
    )
    for match in pattern3.finditer(text):
        # Extract all section numbers - first one and then all captured groups
        section_numbers = [match.group(1)]
        # Find all additional section numbers in the match
        remaining_text = match.group(0)
        # Use a simpler pattern to find all section numbers
        all_nums = re.findall(r'(\d+[A-Z]?)', remaining_text)
        # Check for act name in the match or after
        act_name = "same act"
        if match.group(3):  # Act name captured in pattern
            act_name = match.group(3).strip()
            act_name = re.sub(r'\s+', ' ', act_name).strip()
        else:
            # Check after the match
            after_text = text[match.end():match.end()+200]
            act_match = re.search(r'of\s+(?:the\s+)?([A-Z][^;.,]+(?:Act|Law|Order|Regulation)\s+\d{4})', after_text, re.IGNORECASE)
            if act_match:
                act_name = act_match.group(1).strip()
                act_name = re.sub(r'\s+', ' ', act_name).strip()
        # Add each unique section number
        for sec_num in all_nums:
            sec_num_clean = sec_num.strip()
            if not any(ref['section_number'] == (sec_num_clean if not sec_num_clean.isdigit() else int(sec_num_clean))
                      and ref.get('act', '').lower() == act_name.lower() for ref in references):
                references.append({
                    'section_number': sec_num_clean if not sec_num_clean.isdigit() else int(sec_num_clean),
                    'act': act_name
                })
    
    # Pattern 4: Standalone section reference (section X without explicit act, assume same act)
    # Matches: "see section 2"
    # Matches: "under section 17"
    # Matches: "in section 3"
    # Only if not already captured and not part of "subsection X of that section"
    # IMPORTANT: Must check ahead to ensure there's no act name following
    pattern4 = re.compile(
        r'(?:see|under|in|from|to|by|for|pursuant\s+to|according\s+to|as\s+defined\s+in)\s+section\s+(\d+[A-Z]?)(?:\([^)]+\))?(?:\s+of\s+(?:that|this)\s+act)?',
        re.IGNORECASE
    )
    for match in pattern4.finditer(text):
        section_num = match.group(1).strip()
        # Check context - make sure it's not "subsection X of section Y"
        before_text = text[max(0, match.start()-50):match.start()].lower()
        if 'subsection' not in before_text[-20:]:  # Not immediately preceded by "subsection"
            # CRITICAL: Check ahead to see if there's an act name following
            # If "of [Act Name]" appears after this match, skip it (Pattern 1 or 2 will catch it)
            after_text = text[match.end():match.end()+200]
            has_act_name_after = re.search(
                r'of\s+(?:the\s+)?([A-Z][^;.,]+(?:Act|Law|Order|Regulation)\s+\d{4}|that\s+Act|this\s+Act)',
                after_text,
                re.IGNORECASE
            )
            if not has_act_name_after:
                # Only add if no act name found ahead and not already captured
                if not any(ref['section_number'] == (section_num if not section_num.isdigit() else int(section_num))
                          and ref.get('act', '') == 'same act' for ref in references):
                    references.append({
                        'section_number': section_num if not section_num.isdigit() else int(section_num),
                        'act': 'same act'
                    })
    
    # Pattern 5: Subsection reference that actually refers to another section
    # Matches: "subsection (X) of that section" where "that section" refers to section Y
    # Matches: "subsection (X) of section Y"
    # This is tricky - we need to find what section "that section" refers to
    # For now, we'll skip standalone "subsection (X)" but capture "subsection (X) of section Y"
    pattern5 = re.compile(
        r'subsection\s+\((\d+[A-Z]?)\)\s+of\s+(?:that|this)\s+section',  # subsection (X) of that/this section
        re.IGNORECASE
    )
    # This is context-dependent - we'd need to trace back what "that section" refers to
    # For simplicity, we'll skip these as they're ambiguous
    
    # Pattern 5b: Clear subsection reference to another section
    pattern5b = re.compile(
        r'subsection\s+\((\d+[A-Z]?)\)\s+of\s+section\s+(\d+[A-Z]?)',
        re.IGNORECASE
    )
    for match in pattern5b.finditer(text):
        subsection_num = match.group(1).strip()
        section_num = match.group(2).strip()
        # This refers to subsection X within section Y - we extract section Y
        act_name = "same act"
        after_text = text[match.end():match.end()+100]
        act_match = re.search(r'of\s+(?:the\s+)?([A-Z][^;.,]+(?:Act|Law|Order|Regulation)\s+\d{4})', after_text, re.IGNORECASE)
        if act_match:
            act_name = act_match.group(1).strip()
            act_name = re.sub(r'\s+', ' ', act_name).strip()
        # Add the section reference (not the subsection)
        if not any(ref['section_number'] == (section_num if not section_num.isdigit() else int(section_num))
                  and ref.get('act', '') == act_name for ref in references):
            references.append({
                'section_number': section_num if not section_num.isdigit() else int(section_num),
                'act': act_name
            })
    
    # Remove duplicates while preserving order
    seen = set()
    unique_refs = []
    for ref in references:
        key = (ref['section_number'], ref['act'])
        if key not in seen:
            seen.add(key)
            unique_refs.append(ref)
    
    return unique_refs


def process_obj_for_content_refs_regex(obj):
    """
    Recursively process any dict-like entry with 'content', 'title', or 'additional_content' fields
    using regex-based extraction instead of LLM.
    """
    if not isinstance(obj, dict):
        return

    for key in ['content', 'title', 'additional_content']:
        if key in obj and isinstance(obj[key], str):
            ref_key = f'{key}_references' if key != 'content' else 'references'
            refs = following_regex(obj[key], section_title=obj.get('title', None))
            obj[ref_key] = refs

    # Recursively check nested dicts/lists
    for k, v in obj.items():
        if isinstance(v, dict):
            process_obj_for_content_refs_regex(v)
        elif isinstance(v, list):
            for item in v:
                process_obj_for_content_refs_regex(item)


def process_json_and_save_with_refs_regex(json_path, out_folder):
    """
    Loads the JSON, processes it using regex, and writes new JSON with refs.
    """
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    process_obj_for_content_refs_regex(data)
    base_name = os.path.basename(json_path)
    # Add _regex suffix to distinguish from LLM output
    base_name_no_ext = os.path.splitext(base_name)[0]
    out_path = os.path.join(out_folder, f"{base_name_no_ext}_regex.json")
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Wrote with regex references: {out_path}")


if __name__ == "__main__":
    main()

