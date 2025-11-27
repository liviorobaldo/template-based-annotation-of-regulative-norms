import os
import re
import pandas as pd
import nltk
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords
from nltk.stem import WordNetLemmatizer
from difflib import SequenceMatcher
import string
from collections import defaultdict
import json
import xml.dom.minidom as minidom
import xml.etree.ElementTree as ET
import csv
from util import convert_to_html, normalize_hierarchy_file
from difflib import SequenceMatcher

# Download NLTK resources if not already downloaded
# Handle NLTK data download with SSL certificate issues
import ssl
import urllib.request

def download_nltk_data_with_ssl_fix():
    """Download NLTK data by bypassing SSL certificate verification."""
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    original_urlopen = urllib.request.urlopen
    urllib.request.urlopen = lambda url, *args, **kwargs: original_urlopen(url, *args, context=ssl_context, **kwargs)
    
    try:
        nltk.download('punkt', quiet=True)
        nltk.download('punkt_tab', quiet=True)
        nltk.download('stopwords', quiet=True)
        nltk.download('wordnet', quiet=True)
    except Exception as e:
        print(f"Warning: Could not download some NLTK data: {e}")
    finally:
        urllib.request.urlopen = original_urlopen

try:
    nltk.data.find('tokenizers/punkt')
    nltk.data.find('corpora/stopwords')
    nltk.data.find('corpora/wordnet')
except LookupError:
    download_nltk_data_with_ssl_fix()


def fuzzy_score(text1, text2):
    return SequenceMatcher(None, text1, text2).ratio()

def getSectionUrl(section_id, url):
    """Convert section ID to URL format.
    Handles IDs like:
    - "section-1" -> "section/1"
    - "part-1/section-2" -> "part/1/section/2"
    - "part-1/chapter-1/section-2" -> "part/1/chapter/1/section/2"
    """
    if section_id:
        # Handle IDs with path separators (part/chapter structure)
        if '/' in section_id:
            # Split by '/' and replace '-' with '/' in each part
            parts = section_id.split('/')
            url_parts = [part.replace('-', '/') for part in parts]
            section_path = '/'.join(url_parts)
        else:
            # Simple section ID: replace '-' with '/'
            section_path = section_id.replace('-', '/')
        
        section_url = url + '/' + section_path
        return section_url
    else:
        return section_id

def getSectionIdFromUrl(section_url, base_url):
    """Convert section URL back to section ID format.
    Handles URLs like:
    - "https://www.legislation.gov.uk/ukpga/1989/41/section/1" -> "section-1"
    - "https://www.legislation.gov.uk/ukpga/1989/41/part/1/section/2" -> "part-1/section-2"
    """
    if not section_url or not base_url:
        return None
    
    # Remove base URL prefix
    if section_url.startswith(base_url):
        path = section_url[len(base_url):].strip('/')
        if path:
            # Convert path back to section ID format
            # "section/1" -> "section-1"
            # "part/1/section/2" -> "part-1/section-2"
            parts = path.split('/')
            section_id_parts = []
            i = 0
            while i < len(parts):
                if i + 1 < len(parts):
                    # Combine pairs like "section/1" -> "section-1"
                    section_id_parts.append(f"{parts[i]}-{parts[i+1]}")
                    i += 2
                else:
                    section_id_parts.append(parts[i])
                    i += 1
            return '/'.join(section_id_parts)
    return None

def read_file(file_path):
    """Read a file and return its content."""
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()

def parse_annotations(file_path):
    """Parse annotations from a file and return a list of annotations."""
    content = read_file(file_path)
    # Split by the separator
    annotations = content.split('------------------------')
    # Remove empty annotations
    annotations = [annotation.strip() for annotation in annotations if annotation.strip()]
    return annotations

def extract_section_range_from_filename(filename):
    """Extract section range from annotation filename."""
    # For files like "Sections 1-20.txt"
    sections_match = re.search(r'Sections\s+(\d+)-(\d+)', filename)
    if sections_match:
        start = int(sections_match.group(1))
        end = int(sections_match.group(2))
        return start, end, "section"
    
    # For files like "Artt. 101-120.txt"
    articles_match = re.search(r'Artt\.\s+(\d+)-(\d+)', filename)
    if articles_match:
        start = int(articles_match.group(1))
        end = int(articles_match.group(2))
        return start, end, "section"
    
    return None, None, None

def extract_annotation_parts(annotation):
    """Extract all parts from an annotation."""
    lines = annotation.split('\n')
    parts = {
        'type': '',
        'for': '',
        'to': '',
        'conditions': []
    }
    
    current_part = None
    
    for line in lines:
        if line.startswith('IT IS '):
            parts['type'] = line[6:].strip()
            current_part = None
        elif line.startswith('FOR '):
            parts['for'] = line[4:].strip()
            current_part = None
        elif line.startswith('TO ') or line.startswith('TO,'):
            # Handle both "TO " and "TO," formats
            parts['to'] = line[3:].strip()
            current_part = 'to'
        elif any(line.startswith(keyword) for keyword in ['WHEN/IF/WHERE', 'ONLY IF', 'BEFORE', 'AFTER', 'UNLESS', 'SUBJECT TO']):
            # Extract the condition type and text
            for keyword in ['WHEN/IF/WHERE', 'ONLY IF', 'BEFORE', 'AFTER', 'UNLESS', 'SUBJECT TO']:
                if line.startswith(keyword):
                    condition_text = line[len(keyword):].strip()
                    parts['conditions'].append({
                        'type': keyword,
                        'text': condition_text
                    })
                    current_part = f'condition_{len(parts["conditions"]) - 1}'
                    break
        elif current_part == 'to':
            parts['to'] += ' ' + line.strip()
        elif current_part and current_part.startswith('condition_'):
            condition_idx = int(current_part.split('_')[1])
            parts['conditions'][condition_idx]['text'] += ' ' + line.strip()
    
    return parts

def preprocess_text(text):
    """Preprocess text for better matching while preserving order, without removing stopwords."""
    # Lowercase
    text = text.lower()
    
    # Remove punctuation
    text = text.translate(str.maketrans('', '', string.punctuation))
    
    # Tokenize with fallback method
    try:
        tokens = word_tokenize(text)
    except LookupError:
        import re
        tokens = re.findall(r'\b\w+\b', text)
    
    # DO NOT remove stopwords – keep all tokens
    
    # Lemmatize but preserve order
    try:
        lemmatizer = WordNetLemmatizer()
        tokens = [lemmatizer.lemmatize(token) for token in tokens]
    except LookupError:
        pass
    
    return tokens


def extract_ngrams(tokens, n=3):
    """Extract n-grams from tokens while preserving order."""
    ngrams = []
    
    for i in range(len(tokens) - n + 1):
        ngrams.append(' '.join(tokens[i:i+n]))
    
    return ngrams

def extract_section_text(section_id, hierarchy_json):
    """
    Extract the full text content of a section from the hierarchy JSON.
    Returns the complete text including title, content, subsections, and subitems.
    """
    if not section_id:
        return ""
    
    def find_section_in_hierarchy(section_id, data):
        """Recursively find a section in the hierarchy."""
        if not isinstance(data, dict):
            return None
        
        # Handle section IDs with path separators (e.g., "part-1/section-2")
        if '/' in section_id:
            parts = section_id.split('/')
            current_id = parts[0]
            remaining_path = '/'.join(parts[1:])
        else:
            current_id = section_id
            remaining_path = None
        
        # First, check if current_id is directly in data
        if current_id in data:
            section_data = data[current_id]
            if remaining_path:
                # Continue searching in subsections or subitems
                if 'subsections' in section_data:
                    result = find_section_in_hierarchy(remaining_path, section_data['subsections'])
                    if result:
                        return result
                if 'subitems' in section_data:
                    result = find_section_in_hierarchy(remaining_path, section_data['subitems'])
                    if result:
                        return result
            else:
                return section_data
        
        # Search in nested structures
        # Check in sections dictionary
        if 'sections' in data:
            result = find_section_in_hierarchy(section_id, data['sections'])
            if result:
                return result
        
        # Check in parts -> sections
        if 'parts' in data:
            for part_id, part_data in data['parts'].items():
                result = find_section_in_hierarchy(section_id, part_data)
                if result:
                    return result
        
        # Check in chapters -> sections
        if 'chapters' in data:
            for chapter_id, chapter_data in data['chapters'].items():
                result = find_section_in_hierarchy(section_id, chapter_data)
                if result:
                    return result
        
        # Check in subsections (for nested subsections)
        if 'subsections' in data:
            result = find_section_in_hierarchy(section_id, data['subsections'])
            if result:
                return result
        
        # Check in subitems (for nested subitems)
        if 'subitems' in data:
            result = find_section_in_hierarchy(section_id, data['subitems'])
            if result:
                return result
        
        return None
    
    def extract_text_from_section(section_data):
        return section_data
        """Extract all text content from a section data structure."""
        text_parts = []
        
        # Add number if present
        if 'number' in section_data:
            text_parts.append(section_data['number'])
        
        # Add title if present
        if 'title' in section_data:
            text_parts.append(section_data['title'])
        
        # Add main content if present
        if 'content' in section_data:
            text_parts.append(section_data['content'])
        
        # Add additional_content if present
        if 'additional_content' in section_data:
            if isinstance(section_data['additional_content'], str):
                text_parts.append(section_data['additional_content'])
            elif isinstance(section_data['additional_content'], list):
                text_parts.extend(section_data['additional_content'])
        
        # Add lists if present
        if 'lists' in section_data:
            for list_data in section_data['lists']:
                if 'items' in list_data:
                    text_parts.extend(list_data['items'])
        
        # Recursively add subsections
        if 'subsections' in section_data:
            for subsection_id, subsection_data in section_data['subsections'].items():
                subsection_text = extract_text_from_section(subsection_data)
                if subsection_text:
                    text_parts.append(subsection_text)
        
        # Recursively add subitems
        if 'subitems' in section_data:
            for subitem_id, subitem_data in section_data['subitems'].items():
                subitem_text = extract_text_from_section(subitem_data)
                if subitem_text:
                    text_parts.append(subitem_text)
        
        return ' '.join(str(part) for part in text_parts if part)
    
    # Find the section in the hierarchy
    section_data = find_section_in_hierarchy(section_id, hierarchy_json)
    if section_data:
        text = extract_text_from_section(section_data)
        return text if text else ""
    return ""

def flatten_hierarchy_to_sections(hierarchy_json):
    """
    Convert hierarchical JSON structure to a flat list of sections for matching.
    Handles structures with parts, chapters, and sections.
    Includes main sections, subsections, and sub-items as separate searchable units.
    """
    sections = []
    
    def process_section(section_id, section_data, parent_path=""):
        """Recursively process a section and its subsections/subitems."""
        # Build content for main section
        main_section_content_parts = []
        
        # Add title if it exists
        if 'title' in section_data:
            main_section_content_parts.append(section_data['title'])
        
        # Add main section content if it exists
        if 'content' in section_data:
            main_section_content_parts.append(section_data['content'])
        
        main_section_content = ' '.join(main_section_content_parts)
        
        # Only add main section if it has content
        if main_section_content.strip():
            sections.append({
                'section_id': section_id,
                'content': main_section_content,
                'hierarchy_level': 'section',
                'parent': parent_path
            })
        
        # Process subsections if they exist
        if 'subsections' in section_data:
            for subsection_id, subsection_data in section_data['subsections'].items():
                # Build content from subsection including lists and additional_content
                subsection_content_parts = []
                
                # Add number/title if present
                if 'number' in subsection_data:
                    subsection_content_parts.append(subsection_data['number'])
                if 'title' in subsection_data:
                    subsection_content_parts.append(subsection_data['title'])
                
                # Add main content
                if 'content' in subsection_data:
                    subsection_content_parts.append(subsection_data['content'])
                
                # Add lists if present
                if 'lists' in subsection_data:
                    for list_data in subsection_data['lists']:
                        if 'items' in list_data:
                            # Join list items with separators
                            list_text = ' '.join(list_data['items'])
                            subsection_content_parts.append(list_text)
                
                # Add additional_content if present
                if 'additional_content' in subsection_data:
                    if isinstance(subsection_data['additional_content'], str):
                        subsection_content_parts.append(subsection_data['additional_content'])
                    elif isinstance(subsection_data['additional_content'], list):
                        subsection_content_parts.extend(subsection_data['additional_content'])
                
                subsection_content = ' '.join(subsection_content_parts)
                
                # Only add subsection if it has content
                if subsection_content.strip():
                    sections.append({
                        'section_id': subsection_id,
                        'content': subsection_content,
                        'hierarchy_level': 'subsection',
                        'parent': section_id
                    })
                else:
                    # If subsection has no content, still add it with at least the number/title info
                    # This ensures we don't lose structure
                    sections.append({
                        'section_id': subsection_id,
                        'content': subsection_data.get('number', '') + ' ' + subsection_data.get('title', ''),
                        'hierarchy_level': 'subsection',
                        'parent': section_id
                    })
                
                # Process sub-items if they exist
                if 'subitems' in subsection_data:
                    for subitem_id, subitem_data in subsection_data['subitems'].items():
                        subitem_content_parts = []
                        if 'number' in subitem_data:
                            subitem_content_parts.append(subitem_data['number'])
                        if 'content' in subitem_data:
                            subitem_content_parts.append(subitem_data.get('content', ''))
                        subitem_content = ' '.join(subitem_content_parts)
                        sections.append({
                            'section_id': subitem_id,
                            'content': subitem_content,
                            'hierarchy_level': 'subitem',
                            'parent': subsection_id
                        })
    
    # Handle different JSON structures
    # Case 1: Direct sections at top level (old structure)
    if 'sections' not in hierarchy_json and 'parts' not in hierarchy_json:
        # Assume it's the old structure where sections are directly at top level
        for section_id, section_data in hierarchy_json.items():
            process_section(section_id, section_data)
    
    # Case 2: Sections under "sections" key
    elif 'sections' in hierarchy_json:
        for section_id, section_data in hierarchy_json['sections'].items():
            process_section(section_id, section_data)
    
    # Case 3: Parts -> Chapters -> Sections or Parts -> Sections
    elif 'parts' in hierarchy_json:
        for part_id, part_data in hierarchy_json['parts'].items():
            # Check if parts contain chapters
            if 'chapters' in part_data:
                for chapter_id, chapter_data in part_data['chapters'].items():
                    # Check if chapters contain sections
                    if 'sections' in chapter_data:
                        for section_id, section_data in chapter_data['sections'].items():
                            process_section(section_id, section_data, parent_path=f"{part_id}/{chapter_id}")
                    else:
                        # Chapter itself might be a section-like structure
                        process_section(chapter_id, chapter_data, parent_path=part_id)
            # Check if parts contain sections directly
            elif 'sections' in part_data:
                for section_id, section_data in part_data['sections'].items():
                    process_section(section_id, section_data, parent_path=part_id)
            else:
                # Part itself might be a section-like structure
                process_section(part_id, part_data)
    
    return sections

def find_matching_sections(annotation_parts, sections, section_range, hierarchy_json):
    """
    Find sections that match the annotation parts, returning top 3 main sections
    and matching them with conditions. Works with hierarchical JSON structure.
    """
    # Create section_dict from sections for easy lookup
    section_dict = {section['section_id']: section for section in sections}
    
    # Filter sections based on range only if section_type is not None
    filtered_sections = sections
    if section_range:
        start, end, section_type = section_range
        if section_type is not None:
            filtered_sections = []
            for section in sections:
                section_id = section['section_id']
                # Handle IDs with path separators (e.g., "part-1/section-2")
                if '/' in section_id:
                    # Get the last part which should be the section
                    section_part = section_id.split('/')[-1]
                else:
                    section_part = section_id
                
                # Check if section_type is in the section ID and extract section number
                if section_type in section_part:
                    # Extract number from section part (e.g., "section-2" -> "2")
                    # Handle both "section-2" and "section-2-1" formats
                    match = re.search(r'section-(\d+)', section_part)
                    if match:
                        section_num = int(match.group(1))
                        if start <= section_num <= end:
                            filtered_sections.append(section)
    
    if not filtered_sections:
        filtered_sections = sections
    
        # Store matches for main sections
    main_section_matches = defaultdict(int)

    # Helper: score a piece of text against all filtered sections
    def score_text_against_sections(text, weight_base=1):
        if not text:
            return
        tokens = preprocess_text(text)
        if not tokens:
            return

        grams3 = extract_ngrams(tokens, 3)
        grams5 = extract_ngrams(tokens, 5) if len(tokens) >= 5 else []
        grams7 = extract_ngrams(tokens, 7) if len(tokens) >= 7 else []

        for section in filtered_sections:
            section_tokens = preprocess_text(section['content'].lower())
            section_text = ' '.join(section_tokens)

            for ngram in grams3:
                if ngram in section_text:
                    main_section_matches[section['section_id']] += 1 * weight_base
            for ngram in grams5:
                if ngram in section_text:
                    main_section_matches[section['section_id']] += 2 * weight_base
            for ngram in grams7:
                if ngram in section_text:
                    main_section_matches[section['section_id']] += 3 * weight_base

    # 1) Use type / for / to
    for part_name in ['type', 'for', 'to']:
        if part_name in annotation_parts and annotation_parts[part_name]:
            score_text_against_sections(annotation_parts[part_name])

    # 2) ALSO use all non-UNLESS conditions for main-section matching
    non_unless_conditions = [
        c for c in annotation_parts.get('conditions', [])
        if c.get('type') != 'UNLESS'
    ]
    for cond in non_unless_conditions:
        score_text_against_sections(cond.get('text', ''), weight_base=1)


    # Fallback fuzzy match if nothing matched with n-grams (after processing all parts)
    if not main_section_matches:
        # Combine all annotation parts for fuzzy matching
        combined_text = ' '.join([
            annotation_parts.get('type', ''),
            annotation_parts.get('for', ''),
            annotation_parts.get('to', '')
        ]).strip()
        
        if combined_text:
            for section in filtered_sections:
                section_text = section['content'].lower()
                similarity = SequenceMatcher(None, combined_text.lower(), section_text).ratio()
                if similarity > 0.3:  # Lower threshold for fuzzy matching
                    main_section_matches[section['section_id']] += int(similarity * 10)  # Convert ratio to score
    
    # Get top 3 main sections
    top_main_sections = sorted(main_section_matches.items(), key=lambda x: x[1], reverse=True)[:3]
    top_main_sections = [section_id for section_id, score in top_main_sections if score > 0]
    
    def get_main_section_id(section_id):
        """
        Keep real sections (including lettered ones like section-11A) as-is,
        but collapse true subsections (like section-10-5A or section-10-5-1) to section-10.
        Also works when section IDs are nested in a path (part-1/section-10-5A, etc.).
        """
        if not section_id:
            return section_id

        # Handle IDs with path separators (part/chapter structure) by keeping only the last component
        if '/' in section_id:
            parts = section_id.split('/')
            section_part = parts[-1]

            if section_part.count('-') == 1:
                main_section = section_part
            else:
                segs = section_part.split('-')
                main_section = '-'.join(segs[:2])

            return main_section

        # Some scraped identifiers embed prefixes before the actual "section-" marker.
        if 'section-' in section_id and not section_id.startswith('section-'):
            idx = section_id.rfind('section-')
            tail = section_id[idx:]
            if tail != section_id:
                return get_main_section_id(tail)

        # No '/' in section_id
        # If there is only one dash ("section-11" or "section-11A"), keep as-is.
        if section_id.count('-') == 1:
            return section_id

        # More than one dash: collapse subsections "section-10-5A" → "section-10"
        segs = section_id.split('-')
        if segs[0] == 'section' and len(segs) > 2:
            return '-'.join(segs[:2])

        return section_id


    # Process conditions and add section information directly to them
    updated_conditions = []
    
    # Process non-UNLESS conditions - assign all to the main section like in the old code
    non_unless_conditions = [c for c in annotation_parts['conditions'] if c['type'] != 'UNLESS']
    main_section = top_main_sections[0] if top_main_sections else None
    main_section_id = get_main_section_id(main_section) if main_section else None

    for condition in non_unless_conditions:
        # Create updated condition with section - all non-UNLESS conditions get the main section
        updated_condition = {
            'type': condition['type'],
            'text': condition['text'],
            'section': main_section_id
        }
        
        updated_conditions.append(updated_condition)
    
    # Process UNLESS conditions
    unless_conditions = [c for c in annotation_parts['conditions'] if c['type'] == 'UNLESS']
    for condition in unless_conditions:
        condition_tokens = preprocess_text(condition['text'])
        condition_3grams = extract_ngrams(condition_tokens, 3)
        
        best_match = None
        best_score = -1
        
        # Check each top main section first
        for main_section in top_main_sections:
            section_text = section_dict[main_section]['content'].lower()
            section_tokens = preprocess_text(section_text)
            score = sum(1 for ngram in condition_3grams if ngram in ' '.join(section_tokens))
            
            if score > best_score:
                best_score = score
                best_match = main_section
        
        # If no good match in main sections, check all sections
        if best_score == 0 or best_score == -1:
            for section in sections:
                section_text = section['content'].lower()
                section_tokens = preprocess_text(section_text)
                score = sum(1 for ngram in condition_3grams if ngram in ' '.join(section_tokens))
                
                if score > best_score:
                    best_score = score
                    best_match = section['section_id']
        
        # Map to main section ID
        best_match_main = get_main_section_id(best_match) if best_match else None
        
        # Create updated condition with section
        updated_condition = {
            'type': condition['type'],
            'text': condition['text'],
            'section': best_match_main
        }
        
        updated_conditions.append(updated_condition)
    
    # Map alternative sections to main section IDs
    alternative_main_sections = [get_main_section_id(sid) for sid in top_main_sections[1:]]
    alternative_main_sections = list(dict.fromkeys(alternative_main_sections))  # Remove duplicates while preserving order
    
    return {
        'main_section': main_section_id,
        'alternative_sections': alternative_main_sections,
        'conditions': updated_conditions
    }
def fix_sandwiched_sections(results):
    """
    Light-touch cleanup for obvious glitches in main_section sequence.

    Supports alphanumeric and multi-letter sections like:
        10, 10A, 11B, 4ZA, 14C, etc.

    Rules (using numeric + suffix ordering):

      1) Simple sandwich:
         If we see: x, y, x  and y > x  → middle becomes x
         Examples:
           10, 14A, 10        -> 10, 10, 10
           11, 11C, 11        -> 11, 11, 11
           2, 4ZA, 2          -> 2, 2, 2

      2) Run of big numbers between equal smaller ones:
         left, left, ..., left,  high, high, ..., high,  left, left, ...
         with all high > left → all highs become left.
         Examples:
           2, 2, 2, 4ZA, 4ZA, 2, 2, 2  -> all 2
           10, 10, 14A, 14A, 10        -> all 10

      3) Single forward spike (peak):
         prev < next < cur  → cur is likely wrong.
         Fix cur using its alternatives (if they match prev/next),
         else fall back to next.
         Examples:
           9, 14A, 10         -> 9, 10, 10
           12, 14C, 13        -> 12, 13, 13

      4) Local valley:
         prev > cur < next  → cur is likely wrong.
         Fix cur using its alternatives (if they match prev/next),
         else fall back to prev.
         Example:
           11C, 11C, 11A, 11D -> 11C, 11C, 11C, 11D
    """

    import re

    def parse_key(url):
        """
        Turn section URLs into sortable keys.

          .../section/10     -> (10, (0, ''))
          .../section/10A    -> (10, (1, 'A'))
          .../section/11B    -> (11, (1, 'B'))
          .../section/4ZA    -> (4,  (2, 'ZA'))

        Returns None if the URL doesn't look like a section URL.
        """
        if not url:
            return None

        # Allow any number of letters: 10, 10A, 4ZA, 11AB, ...
        m = re.search(r'/section/(\d+)([A-Za-z]*)', url)
        if not m:
            return None

        num = int(m.group(1))
        suffix = m.group(2).upper() if m.group(2) else ''
        # (length, suffix) to keep ordering sane: 4Z < 4ZA < 4ZB, etc.
        suffix_key = (len(suffix), suffix)
        return (num, suffix_key)

    n = len(results)
    if n < 3:
        return

    # Precompute keys
    keys = [parse_key(r.get("main_section")) for r in results]

    # ---------- PASS 1: simple x, y, x with y > x ----------
    for i in range(1, n - 1):
        prev_key = keys[i - 1]
        cur_key  = keys[i]
        next_key = keys[i + 1]

        if prev_key is None or cur_key is None or next_key is None:
            continue

        # Rule 1: x, y, x with y > x  → y := x
        if prev_key == next_key and cur_key > prev_key:
            correct_url = results[i - 1]["main_section"]
            wrong_url   = results[i]["main_section"]

            results[i]["main_section"] = correct_url
            for cond in results[i].get("conditions", []):
                if cond.get("section") == wrong_url:
                    cond["section"] = correct_url

            keys[i] = prev_key  # keep in sync

    # ---------- PASS 2: run of big numbers between equal smaller ones ----------
    i = 1
    while i < n - 1:
        prev_key = keys[i - 1]
        cur_key  = keys[i]

        if prev_key is None or cur_key is None:
            i += 1
            continue

        # Start of a high run: we just jumped above prev_key
        if cur_key > prev_key:
            left_key = prev_key
            left_url = results[i - 1]["main_section"]

            j = i
            # Move j forward while it stays strictly above left_key
            while j < n and keys[j] is not None and keys[j] > left_key:
                j += 1

            # Now j is first index where keys[j] <= left_key or j == n
            if j < n and keys[j] == left_key:
                # We have: left_key, [>left_key...>left_key], left_key
                for k in range(i, j):
                    wrong_url = results[k]["main_section"]
                    results[k]["main_section"] = left_url

                    for cond in results[k].get("conditions", []):
                        if cond.get("section") == wrong_url:
                            cond["section"] = left_url

                    keys[k] = left_key  # keep in sync

                i = j
                continue

        i += 1

    # ---------- PASS 3: single forward spike prev < next < cur ----------
    for i in range(1, n - 1):
        prev_key = keys[i - 1]
        cur_key  = keys[i]
        next_key = keys[i + 1]

        if prev_key is None or cur_key is None or next_key is None:
            continue

        # prev < next < cur  → cur is a 'forward peak' (like 9,14A,10)
        if prev_key < next_key < cur_key:
            wrong_url = results[i]["main_section"]

            # Try to use one of this row's alternative candidates, if they match neighbors
            alt_urls = results[i].get("_alt_section_urls", []) or []
            alt_pairs = [(parse_key(u), u) for u in alt_urls if parse_key(u) is not None]

            preferred_url = None
            preferred_key = None

            for k_alt, u_alt in alt_pairs:
                if k_alt == prev_key or k_alt == next_key:
                    preferred_url = u_alt
                    preferred_key = k_alt
                    break

            # If no suitable alternative, fall back to the right neighbour (next)
            if preferred_url is None:
                preferred_url = results[i + 1]["main_section"]
                preferred_key = next_key

            results[i]["main_section"] = preferred_url
            for cond in results[i].get("conditions", []):
                if cond.get("section") == wrong_url:
                    cond["section"] = preferred_url

            keys[i] = preferred_key  # keep in sync

    # ---------- PASS 4: local valley prev > cur < next ----------
    for i in range(1, n - 1):
        prev_key = keys[i - 1]
        cur_key  = keys[i]
        next_key = keys[i + 1]

        if prev_key is None or cur_key is None or next_key is None:
            continue

        # valley: prev > cur < next
        if prev_key > cur_key and next_key > cur_key:
            wrong_url = results[i]["main_section"]

            alt_urls = results[i].get("_alt_section_urls", []) or []
            alt_pairs = [(parse_key(u), u) for u in alt_urls if parse_key(u) is not None]

            preferred_url = None
            preferred_key = None

            # Prefer alternative matching prev or next
            for k_alt, u_alt in alt_pairs:
                if k_alt == prev_key or k_alt == next_key:
                    preferred_url = u_alt
                    preferred_key = k_alt
                    break

            # If no suitable alternative, fall back to previous (keep continuity)
            if preferred_url is None:
                preferred_url = results[i - 1]["main_section"]
                preferred_key = prev_key

            results[i]["main_section"] = preferred_url
            for cond in results[i].get("conditions", []):
                if cond.get("section") == wrong_url:
                    cond["section"] = preferred_url

            keys[i] = preferred_key  # keep in sync

def update_main_section(result):
    """
    Modifies the main_section if it satisfies the following conditions:
    1. main_section is not in any condition's section.
    2. Any condition's section is also in alternative_sections.
    
    Args:
        result (dict): The output of find_matching_sections containing:
            - main_section: The primary section identified.
            - alternative_sections: Secondary sections identified.
            - conditions: List of conditions with embedded section information.
    
    Returns:
        dict: Updated result with potentially modified main_section.
    """
    main_section = result.get('main_section')
    alternative_sections = result.get('alternative_sections', [])
    conditions = result.get('conditions', [])
    
    # Extract all condition sections
    condition_sections = [condition.get('section') for condition in conditions if condition.get('section')]
    
    # Condition 1: Check if main_section is not in condition_sections
    if main_section and main_section not in condition_sections:
        # Condition 2: Check if any condition_sections overlap with alternative_sections
        overlapping_sections = [
            section for section in condition_sections
            if section in alternative_sections
        ]
        
        if overlapping_sections:
            # Modify the main_section to the first overlapping section
            new_main_section = overlapping_sections[0]
            result['main_section'] = new_main_section
            
            # Remove the new main_section from alternative_sections
            result['alternative_sections'] = [
                section for section in alternative_sections
                if section != new_main_section
            ]
    
    return result

def recompute_section_texts_from_output(csv_data, hierarchy_json, base_url):
    """
    After `output` JSON has been fixed (e.g. sandwich fix, main_section changes),
    recompute section_texts for each CSV row so it matches the FINAL sections.

    For each non-error row:
      - collect main_section + all condition.section URLs
      - convert URLs back to section IDs
      - extract fresh text via extract_section_text
      - write a new JSON string into row['section_texts']
    """

    for row in csv_data:
        out_str = row.get("output")
        if not out_str:
            continue

        try:
            data = json.loads(out_str)
        except Exception:
            # If output isn't valid JSON, skip
            continue

        # If it's an error row, just keep section_texts empty / as-is
        if isinstance(data, dict) and data.get("error"):
            row["section_texts"] = json.dumps({}, ensure_ascii=False, indent=2)
            continue

        sections_ids = set()

        # 1) main_section URL → section ID
        main_url = data.get("main_section")
        if main_url:
            sid = getSectionIdFromUrl(main_url, base_url)
            if sid:
                sections_ids.add(sid)

        # 2) condition.section URLs → section IDs
        for cond in data.get("conditions", []):
            sec_url = cond.get("section")
            if sec_url:
                sid = getSectionIdFromUrl(sec_url, base_url)
                if sid:
                    sections_ids.add(sid)

        # 3) Extract fresh texts for these corrected section IDs
        section_texts = {}
        for sid in sections_ids:
            text = extract_section_text(sid, hierarchy_json)
            if text:
                section_texts[sid] = text

        # 4) Store back as pretty JSON string, like before
        row["section_texts"] = json.dumps(section_texts, ensure_ascii=False, indent=2)

def main(url, annotation_file, section_json_file, output_json_file_path, output_xml_file_path, output_csv_file_path, mode):
    """
    Main function to process annotations and match them with sections using hierarchical JSON.
    Args:
        url: Base URL for sections
        annotation_file (str): Path to annotation file
        section_json_file (str): Path to hierarchical JSON file
        output_json_file_path (str): Path to save the JSON output file
        output_xml_file_path (str): Path to save the XML output file
        output_csv_file_path (str): Path to save the CSV output file
        mode (str): The mode to run in. Options are:
            - "debug": Include file_name and alternative_Sections_ids in the JSON output
            - "normal": Exclude file_name and alternative_Sections_ids from the JSON output
                        and also produce XML output
    """
    # Ensure hierarchy identifiers are normalized before loading
    normalized_section_json_file = normalize_hierarchy_file(section_json_file)

    # Load hierarchical JSON file
    with open(normalized_section_json_file, 'r', encoding='utf-8') as f:
        hierarchy_json = json.load(f)
    
    # Flatten hierarchy to a list of sections for matching
    sections = flatten_hierarchy_to_sections(hierarchy_json)
    section_dict = {section['section_id']: section for section in sections}

    # Only one annotation file
    annotation_files = [annotation_file]

    results = []
    rows_info = []  # metadata to build CSV later

    input_count = 0
    output_count = 0
    skipped_count = 0
    
    for annotation_file in annotation_files:
        print(f"Processing {annotation_file}...")
        filename = os.path.basename(annotation_file)
        section_range = extract_section_range_from_filename(filename)
        annotations = parse_annotations(annotation_file)
        input_count = len(annotations)
        print(f"\nTotal annotations parsed: {input_count}")
        
        for annotation in annotations:
            # Store original annotation text (cleaned up)
            original_annotation = annotation.strip()
            
            annotation_parts = extract_annotation_parts(annotation)
            
            # Check if annotation is complete
            if not annotation_parts.get('type') or not annotation_parts.get('to'):
                print(f"Warning: Skipping incomplete annotation. Type: {annotation_parts.get('type')}, TO: {annotation_parts.get('to')}")
                skipped_count += 1
                # Still add to CSV with error message
                error_output = json.dumps({
                    'error': 'Incomplete annotation - missing type or TO field',
                    'type': annotation_parts.get('type', ''),
                    'to': annotation_parts.get('to', '')
                }, ensure_ascii=False, indent=2)
                
                rows_info.append({
                    'kind': 'error',
                    'input': original_annotation,
                    'error_output': error_output,
                    'section_texts': {}
                })
                continue


            # Process the annotation
            matching_sections = find_matching_sections(annotation_parts, sections, section_range, hierarchy_json)
            matching_sections = update_main_section(matching_sections)
            main_section_id = matching_sections['main_section']
            updated_conditions = matching_sections['conditions']
            alternative_Sections_ids = matching_sections['alternative_sections']
            annotation_parts['conditions'] = updated_conditions

            if not main_section_id:
                # Fallback: try to get main_section from condition sections
                for cond in updated_conditions:
                    if cond.get('section'):
                        main_section_id = cond['section']
                        matching_sections['main_section'] = main_section_id
                        break

            # Collect all section IDs before converting to URLs
            all_section_ids = set()
            if main_section_id:
                all_section_ids.add(main_section_id)
            
            # Get section IDs from conditions (before URL conversion)
            conditions = annotation_parts['conditions']
            for condition in conditions:
                if condition.get('section'):
                    all_section_ids.add(condition['section'])
            
            # Extract text for all sections
            section_texts = {}
            for section_id in all_section_ids:
                section_text = extract_section_text(section_id, hierarchy_json)
                if section_text:
                    section_texts[section_id] = section_text
            
            # Now convert section IDs to URLs for the output
            for condition in conditions:
                if condition.get('section'):
                    condition['section'] = getSectionUrl(condition.get('section'), url)
            
            # Create result dict - include all annotations even if no main_section is found
            alt_section_urls = [
                getSectionUrl(sec_id, url) for sec_id in alternative_Sections_ids if sec_id
            ]

            result_dict = {
                'main_section': getSectionUrl(main_section_id, url) if main_section_id else None,
                'type': annotation_parts['type'],
                'for': annotation_parts['for'],
                'to': annotation_parts['to'],
                'conditions': conditions,
                # internal: used only by fix_sandwiched_sections
                '_alt_section_urls': alt_section_urls,
            }
            if mode == "debug":
                result_dict['file_name'] = filename
                result_dict['alternative_Sections_ids'] = alternative_Sections_ids

            
            # Count as successfully processed if it has a main_section
            if main_section_id:
                output_count += 1
            
             # Add to results (all processed annotations, even without section)
            results.append(result_dict)
            
            # Record info for CSV; we'll inject the final JSON later,
            # after we've fixed `results` (sandwich rule).
            rows_info.append({
                'kind': 'ok',
                'input': original_annotation,
                'section_texts': section_texts  # this is still a dict
            })

            
    

    # 1) Fix sandwiched big-number sections in `results` (JSON side)
    fix_sandwiched_sections(results)

    # 2) Build JSON output from the fixed `results`
    df = pd.DataFrame(results)
    json_data = df.to_dict(orient='records')
    with open(output_json_file_path, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, ensure_ascii=False, indent=4)
    print(f"Saved {len(results)} records to {output_json_file_path}")

    # 3) Build CSV fresh from `json_data` + `rows_info`
    csv_rows = []
    res_idx = 0  # index into json_data / results

    for info in rows_info:
        if info['kind'] == 'error':
            # Keep the error JSON as-is
            csv_rows.append({
                'input': info['input'],
                'output': info['error_output'],
                'section_texts': json.dumps(info['section_texts'], ensure_ascii=False, indent=2)
            })
        else:  # normal, non-error row
            if res_idx >= len(json_data):
                # Safety; shouldn't normally happen
                break

            out_obj = json_data[res_idx]
            res_idx += 1

            # ---- RECOMPUTE section_texts FROM FINAL OUTPUT ----
            sections_ids = set()

            # main_section URL → section ID
            main_url = out_obj.get("main_section")
            if main_url:
                sid = getSectionIdFromUrl(main_url, url)
                if sid:
                    sections_ids.add(sid)

            # condition.section URLs → section IDs
            for cond in out_obj.get("conditions", []):
                sec_url = cond.get("section")
                if sec_url:
                    sid = getSectionIdFromUrl(sec_url, url)
                    if sid:
                        sections_ids.add(sid)

            # Extract fresh texts for these final section IDs
            fresh_section_texts = []
            for sid in sections_ids:
                # text = extract_section_text(sid, hierarchy_json)
                # if text:
                #     fresh_section_texts[sid] = text
                fresh_section_texts.append(sid)

            csv_rows.append({
                'input': info['input'],
                'output': json.dumps(out_obj, ensure_ascii=False, indent=2),
                'section_texts': json.dumps(fresh_section_texts, ensure_ascii=False, indent=2)
            })


    csv_df = pd.DataFrame(csv_rows)
    csv_df.to_csv(output_csv_file_path, index=False, encoding='utf-8', quoting=csv.QUOTE_ALL)
    print(f"Saved CSV output to {output_csv_file_path} with {len(csv_rows)} rows")
    
    
    # Print statistics
    print("\n" + "="*60)
    print("STATISTICS:")
    print("="*60)
    print(f"Total input annotations: {input_count}")
    print(f"Successfully processed (with section): {output_count}")
    print(f"Processed but no section: {len(results) - output_count}")
    print(f"Skipped (incomplete): {skipped_count}")
    print(f"Total output annotations (in JSON): {len(results)}")
    print("="*60)
    
    if mode == "normal":
        root = ET.Element("annotations")
        for item in json_data:
            annotation = ET.SubElement(root, "annotation")
            section = ET.SubElement(annotation, "section")
            section.text = item['main_section']
            type_elem = ET.SubElement(annotation, "type")
            type_elem.text = item['type']
            for_elem = ET.SubElement(annotation, "for")
            for_html_str = convert_to_html(item['for'], for_elem)
            to_elem = ET.SubElement(annotation, "to")
            to_html_str = convert_to_html(item['to'], to_elem)
            print(to_html_str)
            conditions_elem = ET.SubElement(annotation, "conditions")
            for condition in item.get('conditions', []):
                condition_elem = ET.SubElement(conditions_elem, "condition")
                condition_type = ET.SubElement(condition_elem, "type")
                condition_type.text = condition['type']
                condition_html_str = convert_to_html(condition['text'], condition_elem)
                if 'section' in condition and condition['section']:
                    condition_section = ET.SubElement(condition_elem, "section")
                    condition_section.text = condition['section']
        xml_str = minidom.parseString(ET.tostring(root)).toprettyxml(indent="  ")
        with open(output_xml_file_path, 'w', encoding='utf-8') as f:
            f.write(xml_str)
        print(f"Saved XML output to {output_xml_file_path}")

if __name__ == "__main__":
    current_dir = os.path.dirname(os.path.abspath(__file__))
    annotation_file = os.path.join(current_dir, 'Children Act 1989/chunk9.txt')
    section_json_file = os.path.join(current_dir, 'Children Act 1989/1989_41_chunk_9_sections_hierarchy.json')
    output_json_file_path = os.path.join(current_dir, 'Children Act 1989/outputs/Chunk9.json')
    output_xml_file_path = os.path.join(current_dir, 'Children Act 1989/outputs/Chunk9.xml')
    output_csv_file_path = os.path.join(current_dir, 'Children Act 1989/outputs/Chunk9.csv')
    mode = 'normal'

    url = 'https://www.legislation.gov.uk/ukpga/1989/41'
    main(url, annotation_file, section_json_file, output_json_file_path, output_xml_file_path, output_csv_file_path, mode)
