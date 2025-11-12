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
from util import convert_to_html
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
    if section_id:
        section_id = section_id.replace('-', '/')
        section_url = url + '/' + section_id
        return section_url
    else:
        return section_id

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
        elif line.startswith('TO '):
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
    """Preprocess text for better matching while preserving order."""
    # Lowercase
    text = text.lower()
    
    # Remove punctuation
    text = text.translate(str.maketrans('', '', string.punctuation))
    
    # Tokenize with fallback method
    try:
        tokens = word_tokenize(text)
    except LookupError:
        # Fallback to simple whitespace tokenization if NLTK punkt is not available
        import re
        tokens = re.findall(r'\b\w+\b', text)
    
    # Remove stopwords but preserve order
    try:
        stop_words = set(stopwords.words('english'))
        tokens = [token for token in tokens if token not in stop_words]
    except LookupError:
        # Fallback: use a basic list of common English stopwords
        basic_stopwords = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'must', 'can', 'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they', 'me', 'him', 'her', 'us', 'them'}
        tokens = [token for token in tokens if token not in basic_stopwords]
    
    # Lemmatize but preserve order
    try:
        lemmatizer = WordNetLemmatizer()
        tokens = [lemmatizer.lemmatize(token) for token in tokens]
    except LookupError:
        # Fallback: no lemmatization if WordNet is not available
        pass
    
    return tokens

def extract_ngrams(tokens, n=3):
    """Extract n-grams from tokens while preserving order."""
    ngrams = []
    
    for i in range(len(tokens) - n + 1):
        ngrams.append(' '.join(tokens[i:i+n]))
    
    return ngrams

def flatten_hierarchy_to_sections(hierarchy_json):
    """
    Convert hierarchical JSON structure to a flat list of sections for matching.
    Includes main sections, subsections, and sub-items as separate searchable units.
    """
    sections = []
    
    for section_id, section_data in hierarchy_json.items():
        # Build content for main section
        main_section_content_parts = []
        
        # Add main section content if it exists
        if 'content' in section_data:
            main_section_content_parts.append(section_data['content'])
        
        # If no content but has subsections, we still want to match against subsections
        # So we don't add an empty main section, but we'll still process subsections
        
        main_section_content = ' '.join(main_section_content_parts)
        
        # Only add main section if it has content
        if main_section_content.strip():
            sections.append({
                'section_id': section_id,
                'content': main_section_content,
                'hierarchy_level': 'section',
                'parent': None
            })
        
        # Process subsections if they exist
        if 'subsections' in section_data:
            for subsection_id, subsection_data in section_data['subsections'].items():
                # Build content from subsection including lists and additional_content
                subsection_content_parts = []
                
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
                        'content': subsection_data.get('number', ''),
                        'hierarchy_level': 'subsection',
                        'parent': section_id
                    })
                
                # Process sub-items if they exist
                if 'subitems' in subsection_data:
                    for subitem_id, subitem_data in subsection_data['subitems'].items():
                        subitem_content = subitem_data.get('content', '')
                        sections.append({
                            'section_id': subitem_id,
                            'content': subitem_content,
                            'hierarchy_level': 'subitem',
                            'parent': subsection_id
                        })
    
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
            filtered_sections = [
                section for section in sections
                if section_type in section['section_id'] and
                any(str(num) in section['section_id'].split('-')[-1]
                    for num in range(start, end + 1))
            ]
    
    if not filtered_sections:
        filtered_sections = sections
    
    # Store matches for main sections
    main_section_matches = defaultdict(int)
    
    # Process each annotation part individually
    for part_name in ['type', 'for', 'to']:
        if part_name in annotation_parts and annotation_parts[part_name]:
            part_text = annotation_parts[part_name]
            part_tokens = preprocess_text(part_text)
            
            # Create n-grams for this part
            part_3grams = extract_ngrams(part_tokens, 3)
            part_5grams = extract_ngrams(part_tokens, 5) if len(part_tokens) >= 5 else []
            part_7grams = extract_ngrams(part_tokens, 7) if len(part_tokens) >= 7 else []
            
            # Score sections based on this part
            for section in filtered_sections:
                section_tokens = preprocess_text(section['content'].lower())
                section_text = ' '.join(section_tokens)
                
                # Score based on n-gram matches with progressive weighting
                for ngram in part_3grams:
                    if ngram in section_text:
                        main_section_matches[section['section_id']] += 1
                for ngram in part_5grams:
                    if ngram in section_text:
                        main_section_matches[section['section_id']] += 2
                for ngram in part_7grams:
                    if ngram in section_text:
                        main_section_matches[section['section_id']] += 3

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
    
    # Map subsection/subitem IDs back to main section IDs for return value
    # This ensures we return the top-level section ID (e.g., "section-2" instead of "section-2-1")
    def get_main_section_id(section_id):
        """Get the main section ID from a section/subsection/subitem ID."""
        if section_id:
            # If it's already a main section (just "section-X"), return it
            if re.match(r'section-\d+$', section_id):
                return section_id
            # If it's a subsection (section-X-Y), extract the main section
            match = re.match(r'(section-\d+)', section_id)
            if match:
                return match.group(1)
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


def main(url, annotation_file, section_json_file, output_json_file_path, output_xml_file_path, mode):
    """
    Main function to process annotations and match them with sections using hierarchical JSON.
    Args:
        url: Base URL for sections
        annotation_file (str): Path to annotation file
        section_json_file (str): Path to hierarchical JSON file
        output_json_file_path (str): Path to save the JSON output file
        output_xml_file_path (str): Path to save the XML output file
        mode (str): The mode to run in. Options are:
            - "debug": Include file_name and alternative_Sections_ids in the JSON output
            - "normal": Exclude file_name and alternative_Sections_ids from the JSON output
                        and also produce XML output
    """
    # Load hierarchical JSON file
    with open(section_json_file, 'r', encoding='utf-8') as f:
        hierarchy_json = json.load(f)
    
    # Flatten hierarchy to a list of sections for matching
    sections = flatten_hierarchy_to_sections(hierarchy_json)
    section_dict = {section['section_id']: section for section in sections}

    # Only one annotation file
    annotation_files = [annotation_file]

    results = []
    for annotation_file in annotation_files:
        print(f"Processing {annotation_file}...")
        filename = os.path.basename(annotation_file)
        section_range = extract_section_range_from_filename(filename)
        annotations = parse_annotations(annotation_file)
        print(f"\nTotal annotations parsed: {len(annotations)}")
        for annotation in annotations:
            annotation_parts = extract_annotation_parts(annotation)
            
            # Debug: print annotation parts
            if not annotation_parts.get('type') or not annotation_parts.get('to'):
                print(f"Warning: Skipping incomplete annotation. Type: {annotation_parts.get('type')}, TO: {annotation_parts.get('to')}")
                continue

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

            # Process conditions to add section URLs
            conditions = annotation_parts['conditions']
            for condition in conditions:
                if condition.get('section'):
                    condition['section'] = getSectionUrl(condition.get('section'), url)
            
            # Create result dict - include all annotations even if no main_section is found
            result_dict = {
                'main_section': getSectionUrl(main_section_id, url) if main_section_id else None,
                'type': annotation_parts['type'],
                'for': annotation_parts['for'],
                'to': annotation_parts['to'],
                'conditions': conditions,
            }
            if mode == "debug":
                result_dict['file_name'] = filename
                result_dict['alternative_Sections_ids'] = alternative_Sections_ids
            results.append(result_dict)
    
    df = pd.DataFrame(results)
    json_data = df.to_dict(orient='records')
    with open(output_json_file_path, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, ensure_ascii=False, indent=4)
    print(f"Saved {len(results)} records to {output_json_file_path}")
    
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
    annotation_file = os.path.join(current_dir, 'samle_data/1964_81_part_1.txt')
    section_json_file = os.path.join(current_dir, 'samle_data/1964_81_part_1_sections_hierarchy.json')
    output_json_file_path = os.path.join(current_dir, 'samle_data/outputs/1964_81_part_1.json')
    output_xml_file_path = os.path.join(current_dir, 'samle_data/outputs/1964_81_part_1.xml')
    mode = 'normal'

    url = 'https://www.legislation.gov.uk/ukpga/1964/81'
    main(url, annotation_file, section_json_file, output_json_file_path, output_xml_file_path, mode)

