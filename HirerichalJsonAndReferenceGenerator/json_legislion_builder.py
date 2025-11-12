import json
import re
from bs4 import BeautifulSoup
import os

def extract_sections_with_hierarchy(part_file, output_file=None):
    """
    Extract sections from a part XHTML file with full hierarchical structure preserved.
    Maintains subsections (1, 2, 3...) and sub-items (a, b, c...) as nested structures.
    If output_file is provided, save the JSON there. Otherwise, use the default naming logic.
    """
    try:
        print(f"Opening file: {part_file}")
        # Read the XHTML file
        with open(part_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        print("File read successfully")
        # Parse the XHTML
        soup = BeautifulSoup(content, 'xml')
        print("BeautifulSoup parsing complete")
        
        # Initialize the sections dictionary
        sections = {}
        
        # Find all section anchors with IDs starting with 'section-'
        # Main sections have IDs like: section-1, section-80A, section-2B, etc.
        # Subsections have IDs like: section-1-1, section-80A-7, section-1-2A, etc.
        def is_main_section(section_id):
            if not section_id or not section_id.startswith('section-'):
                return False
            rest = section_id[8:]  # len('section-') = 8
            # If it contains a dash followed by digits or letters, it's a subsection
            if re.match(r'^[\w]+-', rest):
                return False
            return True
        
        section_anchors = soup.find_all('a', id=is_main_section)
        print(f"Found {len(section_anchors)} main section anchors")
        
        for anchor in section_anchors:
            section_id = anchor.get('id')
            print(f"\nProcessing section: {section_id}")
            
            # Find the next h2 element which contains the section info
            section_header = anchor.find_next(['h2', 'h3', 'h4', 'h5', 'h6'])
            if not section_header:
                print(f"No header found for section {section_id}")
                continue
            print(f"Found header for section {section_id}")
            
            # Get section number from the section ID
            section_number = section_id.replace('section-', '')
            print(f"Section number: {section_number}")
            
            # Get section title - specifically look for LegP1GroupTitle span
            title_span = section_header.find('span', class_=re.compile(r'LegP1GroupTitle'))
            if title_span:
                # Get the text content, excluding nested spans like LegExtentRestriction
                # Clone the span and remove unwanted nested elements
                title_clone = BeautifulSoup(str(title_span), 'xml')
                # Remove LegExtentRestriction spans
                for restriction in title_clone.find_all('span', class_=re.compile(r'LegExtentRestriction|btr|bbl|bbr')):
                    restriction.decompose()
                section_title = title_clone.get_text(strip=True)
                # Clean up title - remove redundant text and normalize whitespace
                section_title = re.sub(r'\s+', ' ', section_title).strip()
            else:
                # Fallback: look for any span with text
                title_spans = section_header.find_all('span')
                title_text = []
                for span in title_spans:
                    text = span.get_text(strip=True)
                    if text and text != section_number and 'E+W' not in text and 'U.K.' not in text and not text.startswith('(') and text != 'span':
                        title_text.append(text)
                
                section_title = ' '.join(title_text).strip()
                section_title = re.sub(r'\s+', ' ', section_title).strip()
            
            # Final fallback if no title found
            if not section_title or section_title == 'U.K.' or section_title == section_number:
                section_title = f"Section {section_number}"
            
            print(f"Section title: {section_title}")
            
            # Collect hierarchical content
            hierarchy = {
                'main_content': '',
                'subsections': {}
            }
            
            current = section_header.find_next_sibling()
            current_subsection = None
            current_subitem = None
            processed_elements = set()  # Track elements already processed by lookahead
            
            # Keep going until we hit the next section or run out of siblings
            while current and not (current.name in ['h2', 'h3', 'h4', 'h5', 'h6'] or current.find('a', id=lambda x: x and x and x.startswith('section-') and not re.match(r'section-\d+-\d+[A-Z]*', x))):
                
                # Skip elements that were already processed by lookahead
                if id(current) in processed_elements:
                    current = current.find_next_sibling()
                    continue
                
                # Check for subsection markers (P2No - like (1), (2), etc.)
                if current.name == 'p':
                    # Check if this is a P3Container (sub-item like a, b)
                    if 'LegP3Container' in current.get('class', []):
                        subitem_id_elem = current.find('span', {'class': re.compile(r'LegP3No'), 'id': re.compile(r'section-\d+-\d+-\w+')})
                        if subitem_id_elem and current_subsection:
                            subitem_id = subitem_id_elem.get('id', '')
                            subitem_number = subitem_id_elem.get_text(strip=True)
                            subitem_rhs = current.find('span', class_=re.compile(r'LegP3Text|LegRHS'))
                            subitem_content = subitem_rhs.get_text(strip=True) if subitem_rhs else ''
                            
                            # Add to current subsection's subitems
                            if 'subitems' not in hierarchy['subsections'][current_subsection]:
                                hierarchy['subsections'][current_subsection]['subitems'] = {}
                            hierarchy['subsections'][current_subsection]['subitems'][subitem_id] = {
                                'number': subitem_number,
                                'content': subitem_content
                            }
                    
                    # Check for subsection (P2No - like (1), (2))
                    else:
                        subsection_id_elem = current.find('span', {'class': re.compile(r'LegP2No'), 'id': re.compile(r'section-\d+-\d+[A-Z]*$')})
                        if subsection_id_elem:
                            subsection_id = subsection_id_elem.get('id', '')
                            subsection_number = subsection_id_elem.get_text(strip=True)
                            current_subsection = subsection_id
                            
                            # Extract content from RHS span
                            rhs_span = current.find('span', class_=re.compile(r'LegP2Text|LegRHS'))
                            subsection_content = rhs_span.get_text(strip=True) if rhs_span else ''
                            
                            # Look ahead to collect any lists, continuation paragraphs, or other content
                            # that belongs to this subsection (until next subsection or section)
                            lists = []  # Store lists as structured arrays
                            continuation_texts = []  # Store continuation paragraphs separately
                            elements_to_skip = set()  # Track elements we've processed
                            lookahead = current.find_next_sibling()
                            
                            while lookahead and lookahead.name != 'h2' and not lookahead.find('a', id=lambda x: x and x.startswith('section-') and not re.match(r'section-\d+-\d+', x)):
                                # Stop if we hit a new subsection
                                if lookahead.find('span', {'class': re.compile(r'LegP2No'), 'id': re.compile(r'section-\d+-\d+[A-Z]*$')}):
                                    break
                                # Stop if we hit a P3Container (sub-item) - those will be handled separately
                                if 'LegP3Container' in lookahead.get('class', []):
                                    break
                                
                                # Collect list items (ul, ol) as structured arrays
                                if lookahead.name in ['ul', 'ol']:
                                    list_items = []
                                    # Find all li elements (including nested ones)
                                    for li in lookahead.find_all('li'):
                                        # Get all text from this list item, including nested content
                                        item_text = li.get_text(separator=' ', strip=True)
                                        if item_text:
                                            list_items.append(item_text)
                                    if list_items:
                                        lists.append({
                                            'type': lookahead.name,  # 'ul' or 'ol'
                                            'items': list_items
                                        })
                                        elements_to_skip.add(id(lookahead))
                                # Collect continuation paragraphs
                                elif lookahead.name == 'p':
                                    # Check if it's continuation text - has LegP2Text or LegRHS but NO LegP2No
                                    # Look for spans with classes containing LegP2Text or LegRHS
                                    has_p2_text = False
                                    has_p2_no = False
                                    
                                    for span in lookahead.find_all('span'):
                                        span_classes = span.get('class', [])
                                        if isinstance(span_classes, list):
                                            class_str = ' '.join(span_classes)
                                        else:
                                            class_str = str(span_classes)
                                        
                                        if re.search(r'LegP2Text|LegRHS', class_str):
                                            has_p2_text = True
                                        if re.search(r'LegP2No', class_str):
                                            has_p2_no = True
                                    
                                    if has_p2_text and not has_p2_no:
                                        cont_text = lookahead.get_text(strip=True)
                                        if cont_text:
                                            continuation_texts.append(cont_text)
                                            elements_to_skip.add(id(lookahead))
                                
                                lookahead = lookahead.find_next_sibling()
                            
                            # Build subsection structure with lists and continuation text
                            subsection_structure = {
                                'number': subsection_number
                            }
                            
                            # Add main content if exists
                            if subsection_content:
                                subsection_structure['content'] = subsection_content
                            
                            # Add lists if any
                            if lists:
                                subsection_structure['lists'] = lists
                            
                            # Add continuation texts if any
                            if continuation_texts:
                                if len(continuation_texts) == 1:
                                    subsection_structure['continuation'] = continuation_texts[0]
                                else:
                                    subsection_structure['continuation'] = continuation_texts
                            
                            # Mark elements to skip in main loop
                            processed_elements.update(elements_to_skip)
                            
                            hierarchy['subsections'][subsection_id] = subsection_structure
                        else:
                            # Check for continuation text after sub-items (LegRHS LegP2Text)
                            if current_subsection and current.find('span', class_=re.compile(r'LegP2Text|LegRHS')):
                                rhs_span = current.find('span', class_=re.compile(r'LegP2Text|LegRHS'))
                                if rhs_span and not current.find('span', {'class': re.compile(r'LegP2No')}):
                                    continuation_text = rhs_span.get_text(strip=True)
                                    if continuation_text:
                                        # Check if already captured
                                        current_sub = hierarchy['subsections'][current_subsection]
                                        if 'continuation' in current_sub:
                                            # Already has continuation, append to it
                                            if isinstance(current_sub['continuation'], list):
                                                current_sub['continuation'].append(continuation_text)
                                            else:
                                                current_sub['continuation'] = [current_sub['continuation'], continuation_text]
                                        else:
                                            # Add to additional_content instead of merging into content
                                            if 'additional_content' not in current_sub:
                                                current_sub['additional_content'] = []
                                            if continuation_text not in current_sub.get('additional_content', []):
                                                current_sub['additional_content'].append(continuation_text)
                            # Check for standalone content (no subsection marker)
                            elif not current_subsection:
                                rhs_span = current.find('span', class_=re.compile(r'LegP1Text|LegRHS'))
                                if rhs_span:
                                    span_classes = rhs_span.get('class', [])
                                    if isinstance(span_classes, list):
                                        has_p1_text = 'LegP1Text' in span_classes
                                    else:
                                        has_p1_text = 'LegP1Text' in str(span_classes)
                                    
                                    if has_p1_text:
                                        text = rhs_span.get_text(strip=True)
                                        if text and 'E+W' not in text:
                                            if hierarchy['main_content']:
                                                hierarchy['main_content'] += '\n' + text
                                            else:
                                                hierarchy['main_content'] = text
                            # Fallback: capture any other content that wasn't matched above
                            else:
                                # If we're in a subsection context but this element wasn't matched, 
                                # try to capture it as additional content
                                if current_subsection and current.name == 'p':
                                    text = current.get_text(strip=True)
                                    if text and 'E+W' not in text and 'U.K.' not in text:
                                        # Store as additional_unmatched_content
                                        current_sub = hierarchy['subsections'][current_subsection]
                                        if 'additional_content' not in current_sub:
                                            current_sub['additional_content'] = []
                                        if text not in str(current_sub.get('content', '')) and text not in current_sub.get('additional_content', []):
                                            current_sub['additional_content'].append(text)
                                # If not in subsection, add to main content
                                elif not current_subsection:
                                    text = current.get_text(strip=True)
                                    if text and 'E+W' not in text and 'U.K.' not in text:
                                        if hierarchy['main_content']:
                                            hierarchy['main_content'] += '\n' + text
                                        else:
                                            hierarchy['main_content'] = text
                
                current = current.find_next_sibling()
            
            # Build the section entry
            section_entry = {
                'number': section_number,
                'title': section_title
            }
            
            # Add main content if exists
            if hierarchy['main_content']:
                section_entry['content'] = hierarchy['main_content']
            
            # Clean up subsections - keep additional_content and continuation separate to preserve hierarchy
            if hierarchy['subsections']:
                for sub_id, sub_data in hierarchy['subsections'].items():
                    # If continuation field exists, rename it to additional_content for consistency
                    if 'continuation' in sub_data and 'additional_content' not in sub_data:
                        sub_data['additional_content'] = sub_data['continuation']
                        del sub_data['continuation']
                    elif 'continuation' in sub_data and 'additional_content' in sub_data:
                        # Merge continuation into additional_content
                        if isinstance(sub_data['continuation'], list):
                            sub_data['additional_content'].extend(sub_data['continuation'])
                        else:
                            sub_data['additional_content'].append(sub_data['continuation'])
                        del sub_data['continuation']
                    
                    # Clean up additional_content format and remove from content if present
                    if 'additional_content' in sub_data:
                        # Remove additional_content text from content field if it exists there
                        if 'content' in sub_data:
                            content_text = sub_data['content']
                            if isinstance(sub_data['additional_content'], list):
                                for additional_text in sub_data['additional_content']:
                                    # Remove the additional content from the content field
                                    if additional_text in content_text:
                                        content_text = content_text.replace(additional_text, '').strip()
                                sub_data['content'] = content_text
                            else:
                                # Single additional_content item
                                if sub_data['additional_content'] in content_text:
                                    sub_data['content'] = content_text.replace(sub_data['additional_content'], '').strip()
                        
                        # Clean up additional_content format
                        if isinstance(sub_data['additional_content'], list) and len(sub_data['additional_content']) == 1:
                            sub_data['additional_content'] = sub_data['additional_content'][0]
                        # Remove duplicates
                        elif isinstance(sub_data['additional_content'], list):
                            # Remove duplicate strings while preserving order
                            seen = set()
                            unique_list = []
                            for item in sub_data['additional_content']:
                                if item not in seen:
                                    seen.add(item)
                                    unique_list.append(item)
                            sub_data['additional_content'] = unique_list
                
                section_entry['subsections'] = hierarchy['subsections']
            elif not hierarchy['main_content']:
                # If no subsections and no main content, collect all paragraph text as flat content
                content = []
                current = section_header.find_next_sibling()
                while current and not (current.name in ['h2', 'h3', 'h4', 'h5', 'h6'] or current.find('a', id=lambda x: x and x and x.startswith('section-') and not re.match(r'section-\d+-\d+[A-Z]*', x))):
                    if current.name == 'p':
                        text = current.get_text(strip=True)
                        if text and 'E+W' not in text and 'U.K.' not in text:
                            content.append(text)
                    current = current.find_next_sibling()
                if content:
                    section_entry['content'] = '\n'.join(content)
            
            # Add to sections dictionary
            sections[section_id] = section_entry
            print(f"Added section {section_id} with {len(hierarchy['subsections'])} subsections")
        
        print(f"\nTotal sections processed: {len(sections)}")
        
        # Save to JSON file using the provided output_file or the part directory name
        if output_file is None:
            part_dir = os.path.basename(os.path.dirname(part_file))
            output_file = os.path.join(os.path.dirname(part_file), f"{part_dir}_sections.json")
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(sections, f, indent=4, ensure_ascii=False)
        print(f"Saved sections with hierarchy to {output_file}")
        
        return sections
        
    except Exception as e:
        print(f"Error extracting sections from {part_file}: {str(e)}")
        import traceback
        traceback.print_exc()
        return {}

def _unwrap_formatting_tags(element_or_soup):
    """
    Helper function to unwrap bold/italic/strong/em tags while preserving their text content.
    This ensures text like '<b>S</b>' becomes 'S' in the extracted text.
    """
    if hasattr(element_or_soup, 'find_all'):
        soup_elem = element_or_soup
    else:
        soup_elem = BeautifulSoup(str(element_or_soup), 'xml')
    
    # Replace bold/italic tags with their text content (unwind them)
    for bold_tag in soup_elem.find_all(['b', 'strong']):
        bold_tag.replace_with(bold_tag.get_text())
    for italic_tag in soup_elem.find_all(['i', 'em']):
        italic_tag.replace_with(italic_tag.get_text())
    
    return soup_elem

def _extract_section_hierarchy(section_anchor, soup):
    """
    Helper function to extract hierarchical content for a single section.
    Returns a section entry dictionary with number, title, content, and subsections.
    """
    section_id = section_anchor.get('id')
    
    # Find the next heading element (h2, h3, h4, h5, h6) which contains the section info
    section_header = section_anchor.find_next(['h2', 'h3', 'h4', 'h5', 'h6'])
    if not section_header:
        return None
    
    # Get section number from the section ID
    section_number = section_id.replace('section-', '')
    
    # Get section title - specifically look for LegP1GroupTitle span
    title_span = section_header.find('span', class_=re.compile(r'LegP1GroupTitle'))
    if title_span:
        # Get the text content, excluding nested spans like LegExtentRestriction
        title_clone = BeautifulSoup(str(title_span), 'xml')
        # Remove LegExtentRestriction spans and section number spans, but preserve bold/italic text
        for restriction in title_clone.find_all('span', class_=re.compile(r'LegExtentRestriction|btr|bbl|bbr|LegP1No')):
            restriction.decompose()
        # Unwrap formatting tags (bold/italic)
        title_clone = _unwrap_formatting_tags(title_clone)
        section_title = title_clone.get_text(strip=True)
        # Clean up title - remove redundant text and normalize whitespace
        section_title = re.sub(r'\s+', ' ', section_title).strip()
        # Remove section number if it accidentally got included
        if section_title.startswith(section_number + ' '):
            section_title = section_title[len(section_number)+1:].strip()
        if section_title.endswith(' ' + section_number):
            section_title = section_title[:-len(section_number)-1].strip()
    else:
        # Fallback: look for any span with text, but exclude the section number span
        title_spans = section_header.find_all('span')
        title_text = []
        for span in title_spans:
            # Skip the section number span
            if 'LegP1No' in span.get('class', []):
                continue
            # Clone span and unwrap bold/italic tags
            span_clone = BeautifulSoup(str(span), 'xml')
            span_clone = _unwrap_formatting_tags(span_clone)
            text = span_clone.get_text(strip=True)
            if text and text != section_number and 'E+W' not in text and 'U.K.' not in text and not text.startswith('(') and text != 'span' and not text == section_number:
                title_text.append(text)
        
        section_title = ' '.join(title_text).strip()
        section_title = re.sub(r'\s+', ' ', section_title).strip()
    
    # Final fallback if no title found
    if not section_title or section_title == 'U.K.' or section_title == section_number or len(section_title.strip()) == 0:
        section_title = f"Section {section_number}"
    
    hierarchy = {
        'main_content': '',
        'subsections': {}
    }
    
    current = section_header.find_next_sibling()
    current_subsection = None
    processed_elements = set()
    
    # Helper function to check if a section ID is a main section (not a subsection)
    def is_main_section_id(section_id):
        if not section_id or not section_id.startswith('section-'):
            return False
        rest = section_id[8:]  # len('section-') = 8
        # If it contains a dash after the section identifier, it's a subsection
        if re.match(r'^[\w]+-', rest):
            return False
        return True
    
    # Keep going until we hit the next section, part, chapter, or run out of siblings
    while current and not (current.name in ['h2', 'h3', 'h4', 'h5', 'h6'] or 
                           current.find('a', id=lambda x: (x and x.startswith('part-')) or (x and x.startswith('chapter-')) or (x and is_main_section_id(x)))):
        # Skip elements that were already processed by lookahead
        if id(current) in processed_elements:
            current = current.find_next_sibling()
            continue
        
        # Check for subsection markers (P2No - like (1), (2), etc.)
        if current.name == 'p':
            # Check if this is a P3Container (sub-item like a, b)
            if 'LegP3Container' in current.get('class', []):
                subitem_id_elem = current.find('span', {'class': re.compile(r'LegP3No'), 'id': re.compile(r'section-\d+-\d+-\w+')})
                if subitem_id_elem and current_subsection:
                    subitem_id = subitem_id_elem.get('id', '')
                    subitem_number = subitem_id_elem.get_text(strip=True)
                    subitem_rhs = current.find('span', class_=re.compile(r'LegP3Text|LegRHS'))
                    if subitem_rhs:
                        subitem_rhs_clone = BeautifulSoup(str(subitem_rhs), 'xml')
                        subitem_rhs_clone = _unwrap_formatting_tags(subitem_rhs_clone)
                        subitem_content = subitem_rhs_clone.get_text(strip=True)
                    else:
                        subitem_content = ''
                    
                    # Add to current subsection's subitems
                    if 'subitems' not in hierarchy['subsections'][current_subsection]:
                        hierarchy['subsections'][current_subsection]['subitems'] = {}
                    hierarchy['subsections'][current_subsection]['subitems'][subitem_id] = {
                        'number': subitem_number,
                        'content': subitem_content
                    }
            
            # Check for subsection (P2No - like (1), (2))
            else:
                subsection_id_elem = current.find('span', {'class': re.compile(r'LegP2No'), 'id': re.compile(r'section-\d+-\d+[A-Z]*$')})
                if subsection_id_elem:
                    subsection_id = subsection_id_elem.get('id', '')
                    subsection_number = subsection_id_elem.get_text(strip=True)
                    current_subsection = subsection_id
                    
                    # Extract content from RHS span
                    rhs_span = current.find('span', class_=re.compile(r'LegP2Text|LegRHS'))
                    if rhs_span:
                        rhs_clone = BeautifulSoup(str(rhs_span), 'xml')
                        rhs_clone = _unwrap_formatting_tags(rhs_clone)
                        subsection_content = rhs_clone.get_text(strip=True)
                    else:
                        subsection_content = ''
                    
                    # Look ahead to collect any lists, continuation paragraphs, or other content
                    lists = []
                    continuation_texts = []
                    elements_to_skip = set()
                    lookahead = current.find_next_sibling()
                    
                    while lookahead and lookahead.name not in ['h2', 'h3', 'h4', 'h5', 'h6'] and not lookahead.find('a', id=lambda x: (x and x.startswith('part-')) or (x and x.startswith('chapter-')) or (x and is_main_section_id(x))):
                        # Stop if we hit a new subsection
                        if lookahead.find('span', {'class': re.compile(r'LegP2No'), 'id': re.compile(r'section-\d+-\d+[A-Z]*$')}):
                            break
                        if 'LegP3Container' in lookahead.get('class', []):
                            break
                        
                        # Collect list items
                        if lookahead.name in ['ul', 'ol']:
                            list_items = []
                            for li in lookahead.find_all('li'):
                                item_text = li.get_text(separator=' ', strip=True)
                                if item_text:
                                    list_items.append(item_text)
                            if list_items:
                                lists.append({
                                    'type': lookahead.name,
                                    'items': list_items
                                })
                                elements_to_skip.add(id(lookahead))
                        # Collect continuation paragraphs
                        elif lookahead.name == 'p':
                            has_p2_text = False
                            has_p2_no = False
                            
                            for span in lookahead.find_all('span'):
                                span_classes = span.get('class', [])
                                class_str = ' '.join(span_classes) if isinstance(span_classes, list) else str(span_classes)
                                
                                if re.search(r'LegP2Text|LegRHS', class_str):
                                    has_p2_text = True
                                if re.search(r'LegP2No', class_str):
                                    has_p2_no = True
                            
                            if has_p2_text and not has_p2_no:
                                cont_text = lookahead.get_text(strip=True)
                                if cont_text:
                                    continuation_texts.append(cont_text)
                                    elements_to_skip.add(id(lookahead))
                        
                        lookahead = lookahead.find_next_sibling()
                    
                    # Build subsection structure
                    subsection_structure = {'number': subsection_number}
                    if subsection_content:
                        subsection_structure['content'] = subsection_content
                    if lists:
                        subsection_structure['lists'] = lists
                    if continuation_texts:
                        subsection_structure['continuation'] = continuation_texts[0] if len(continuation_texts) == 1 else continuation_texts
                    
                    processed_elements.update(elements_to_skip)
                    hierarchy['subsections'][subsection_id] = subsection_structure
                else:
                    # Check for continuation text after sub-items
                    if current_subsection and current.find('span', class_=re.compile(r'LegP2Text|LegRHS')):
                        rhs_span = current.find('span', class_=re.compile(r'LegP2Text|LegRHS'))
                        if rhs_span and not current.find('span', {'class': re.compile(r'LegP2No')}):
                            rhs_clone = BeautifulSoup(str(rhs_span), 'xml')
                            rhs_clone = _unwrap_formatting_tags(rhs_clone)
                            continuation_text = rhs_clone.get_text(strip=True)
                            if continuation_text:
                                current_sub = hierarchy['subsections'][current_subsection]
                                if 'continuation' in current_sub:
                                    if isinstance(current_sub['continuation'], list):
                                        current_sub['continuation'].append(continuation_text)
                                    else:
                                        current_sub['continuation'] = [current_sub['continuation'], continuation_text]
                                else:
                                    if 'additional_content' not in current_sub:
                                        current_sub['additional_content'] = []
                                    if continuation_text not in current_sub.get('additional_content', []):
                                        current_sub['additional_content'].append(continuation_text)
                    # Check for standalone content
                    elif not current_subsection:
                        rhs_span = current.find('span', class_=re.compile(r'LegP1Text|LegRHS'))
                        if rhs_span:
                            span_classes = rhs_span.get('class', [])
                            has_p1_text = 'LegP1Text' in (span_classes if isinstance(span_classes, list) else str(span_classes))
                            
                            if has_p1_text:
                                rhs_clone = BeautifulSoup(str(rhs_span), 'xml')
                                rhs_clone = _unwrap_formatting_tags(rhs_clone)
                                text = rhs_clone.get_text(strip=True)
                                if text and 'E+W' not in text:
                                    if hierarchy['main_content']:
                                        hierarchy['main_content'] += '\n' + text
                                    else:
                                        hierarchy['main_content'] = text
                    # Fallback: capture other content
                    else:
                        if current_subsection and current.name == 'p':
                            text = current.get_text(strip=True)
                            if text and 'E+W' not in text and 'U.K.' not in text:
                                current_sub = hierarchy['subsections'][current_subsection]
                                if 'additional_content' not in current_sub:
                                    current_sub['additional_content'] = []
                                if text not in str(current_sub.get('content', '')) and text not in current_sub.get('additional_content', []):
                                    current_sub['additional_content'].append(text)
                        elif not current_subsection:
                            text = current.get_text(strip=True)
                            if text and 'E+W' not in text and 'U.K.' not in text:
                                if hierarchy['main_content']:
                                    hierarchy['main_content'] += '\n' + text
                                else:
                                    hierarchy['main_content'] = text
        
        current = current.find_next_sibling()
    
    # Build the section entry
    section_entry = {
        'number': section_number,
        'title': section_title
    }
    
    # Add main content if exists
    if hierarchy['main_content']:
        section_entry['content'] = hierarchy['main_content']
    
    # Clean up subsections
    if hierarchy['subsections']:
        for sub_id, sub_data in hierarchy['subsections'].items():
            if 'continuation' in sub_data and 'additional_content' not in sub_data:
                sub_data['additional_content'] = sub_data['continuation']
                del sub_data['continuation']
            elif 'continuation' in sub_data and 'additional_content' in sub_data:
                if isinstance(sub_data['continuation'], list):
                    sub_data['additional_content'].extend(sub_data['continuation'])
                else:
                    sub_data['additional_content'].append(sub_data['continuation'])
                del sub_data['continuation']
            
            if 'additional_content' in sub_data:
                if 'content' in sub_data:
                    content_text = sub_data['content']
                    if isinstance(sub_data['additional_content'], list):
                        for additional_text in sub_data['additional_content']:
                            if additional_text in content_text:
                                content_text = content_text.replace(additional_text, '').strip()
                        sub_data['content'] = content_text
                    else:
                        if sub_data['additional_content'] in content_text:
                            sub_data['content'] = content_text.replace(sub_data['additional_content'], '').strip()
                
                if isinstance(sub_data['additional_content'], list) and len(sub_data['additional_content']) == 1:
                    sub_data['additional_content'] = sub_data['additional_content'][0]
                elif isinstance(sub_data['additional_content'], list):
                    seen = set()
                    unique_list = []
                    for item in sub_data['additional_content']:
                        if item not in seen:
                            seen.add(item)
                            unique_list.append(item)
                    sub_data['additional_content'] = unique_list
        
        section_entry['subsections'] = hierarchy['subsections']
    elif not hierarchy['main_content']:
        # If no subsections and no main content, collect all paragraph text
        content = []
        current = section_header.find_next_sibling()
        while current and not (current.name in ['h2', 'h3', 'h4', 'h5', 'h6'] or 
                               current.find('a', id=lambda x: (x and x.startswith('part-')) or (x and x.startswith('chapter-')) or (x and is_main_section_id(x)))):
            if current.name == 'p':
                text = current.get_text(strip=True)
                if text and 'E+W' not in text and 'U.K.' not in text:
                    content.append(text)
            current = current.find_next_sibling()
        if content:
            section_entry['content'] = '\n'.join(content)
    
    return section_entry

def extract_legaldocML_hierarchy(part_file, output_file=None):
    """
    Extract sections from a LegalDocML XHTML file with full hierarchical structure preserved.
    Automatically detects and handles:
    - Acts with Parts -> Chapters -> Sections
    - Acts with Parts -> Sections  
    - Acts with Sections directly (no parts)
    - Sections with subsections and sub-items are always preserved
    
    Structure adapts to document structure automatically.
    
    If output_file is provided, save the JSON there. Otherwise, use the default naming logic.
    """
    try:
        print(f"Opening file: {part_file}")
        # Read the XHTML file
        with open(part_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        print("File read successfully")
        # Parse the XHTML
        soup = BeautifulSoup(content, 'xml')
        print("BeautifulSoup parsing complete")
        
        # Initialize the structure - will be populated based on what exists
        result = {}
        
        # Find all section anchors first (always needed)
        # Main sections have IDs like: section-1, section-80A, section-2B, etc.
        # Subsections have IDs like: section-1-1, section-80A-7, section-1-2A, etc.
        # Sub-items have IDs like: section-1-1-a, section-80A-7-b, etc.
        # So main sections are those that don't have a second number/letter after a dash
        def is_main_section(section_id):
            if not section_id or not section_id.startswith('section-'):
                return False
            # Remove 'section-' prefix
            rest = section_id[8:]  # len('section-') = 8
            # If it contains a dash followed by digits or letters, it's a subsection or sub-item
            # Pattern: section-NUMBERLETTERS-anything means it's not a main section
            if re.match(r'^[\w]+-', rest):
                return False
            return True
        
        all_section_anchors = soup.find_all('a', id=is_main_section)
        print(f"Found {len(all_section_anchors)} sections total")
        
        # Find all part anchors - only actual parts, not part-X-chapter-Y
        # Parts should be just "part-1", "part-2", etc., not "part-1-chapter-1"
        def is_actual_part(part_id):
            if not part_id or not part_id.startswith('part-'):
                return False
            rest = part_id[5:]  # len('part-') = 5
            # If it contains "-chapter-", it's not a real part, it's a chapter anchor
            if '-chapter-' in rest:
                return False
            return True
        
        part_anchors = soup.find_all('a', id=is_actual_part)
        print(f"Found {len(part_anchors)} parts")
        
        # Decide structure based on what exists
        if len(part_anchors) > 0:
            # Act has parts - use parts structure
            result['parts'] = {}
            
            # Process each part
            for part_anchor in part_anchors:
                part_id = part_anchor.get('id')
                print(f"\nProcessing part: {part_id}")
                
                # Find the part header (h2 with LegPart or LegPartFirst class)
                part_header = part_anchor.find_next(['h2', 'h3'])
                if not part_header:
                    print(f"No header found for part {part_id}")
                    continue
                
                # Extract part number and title
                part_no_span = part_header.find('span', class_=re.compile(r'LegPartNo'))
                if part_no_span:
                    # Clone and clean up
                    part_no_clone = BeautifulSoup(str(part_no_span), 'xml')
                    for restriction in part_no_clone.find_all('span', class_=re.compile(r'LegExtentRestriction|btr|bbl|bbr')):
                        restriction.decompose()
                    part_no_clone = _unwrap_formatting_tags(part_no_clone)
                    part_number = part_no_clone.get_text(strip=True)
                else:
                    part_number = part_id.replace('part-', '')
                
                part_title_span = part_header.find('span', class_=re.compile(r'LegPartTitle'))
                if part_title_span:
                    part_title_clone = BeautifulSoup(str(part_title_span), 'xml')
                    part_title_clone = _unwrap_formatting_tags(part_title_clone)
                    part_title = part_title_clone.get_text(strip=True)
                else:
                    part_title = ''
                
                # Clean up part number and title
                part_number = re.sub(r'\s+', ' ', part_number).strip()
                part_title = re.sub(r'\s+', ' ', part_title).strip()
                
                print(f"Part number: {part_number}, title: {part_title}")
                
                # Initialize part structure
                part_structure = {
                    'number': part_number,
                    'title': part_title,
                    'chapters': {},
                    'sections': {}
                }
                
                # Also find all part anchors to determine boundaries (use the same filter)
                all_part_anchors = soup.find_all('a', id=is_actual_part)
                current_part_index = all_part_anchors.index(part_anchor) if part_anchor in all_part_anchors else -1
                next_part_anchor = all_part_anchors[current_part_index + 1] if current_part_index >= 0 and current_part_index + 1 < len(all_part_anchors) else None
                
                # Find all section anchors that belong to this part
                sections_in_part = []
                for section_anchor in all_section_anchors:
                    # Check if this section comes after the current part and before the next part (or end of doc)
                    section_id = section_anchor.get('id')
                    
                    # Simple check: if there's a next part, check if section comes before it
                    if next_part_anchor:
                        # Get all elements and check their order
                        all_elements = list(soup.find_all(['a']))
                        part_idx = all_elements.index(part_anchor) if part_anchor in all_elements else -1
                        section_idx = all_elements.index(section_anchor) if section_anchor in all_elements else -1
                        next_part_idx = all_elements.index(next_part_anchor) if next_part_anchor in all_elements else -1
                        
                        if part_idx >= 0 and section_idx >= 0 and next_part_idx >= 0:
                            if part_idx < section_idx < next_part_idx:
                                sections_in_part.append(section_anchor)
                    else:
                        # No next part, check if section comes after current part
                        all_elements = list(soup.find_all(['a']))
                        part_idx = all_elements.index(part_anchor) if part_anchor in all_elements else -1
                        section_idx = all_elements.index(section_anchor) if section_anchor in all_elements else -1
                        if part_idx >= 0 and section_idx >= 0 and section_idx > part_idx:
                            sections_in_part.append(section_anchor)
                
                print(f"Found {len(sections_in_part)} sections in part {part_id}")
                
                # Find chapters within this part
                # Chapters are marked with: <a id="part-X-chapter-Y"/> followed by <h3 class="LegChapter">
                # Or h3/h4 with LegChapterTitle/LegChapterNo spans
                chapters_in_part = []
                
                # Find chapter anchors first (id="part-X-chapter-Y")
                chapter_anchors = soup.find_all('a', id=lambda x: x and x.startswith('part-') and '-chapter-' in x)
                
                # Also find h3/h4 headings that might be chapters
                all_headings = soup.find_all(['h3', 'h4'])
                
                # Determine the range of this part
                part_start_idx = None
                part_end_idx = None
                
                all_anchors = list(soup.find_all('a'))
                try:
                    part_start_idx = all_anchors.index(part_anchor)
                    if next_part_anchor:
                        part_end_idx = all_anchors.index(next_part_anchor)
                except:
                    pass
                
                # Process chapter anchors (most reliable way to find chapters)
                for chapter_anchor in chapter_anchors:
                    chapter_id_full = chapter_anchor.get('id')
                    # Extract chapter identifier: "part-1-chapter-1" -> "1"
                    if '-chapter-' in chapter_id_full:
                        # Check if this chapter belongs to current part
                        chapter_part_id = chapter_id_full.split('-chapter-')[0]
                        if chapter_part_id == part_id:
                            # Find the chapter header after this anchor
                            chapter_header = chapter_anchor.find_next(['h3', 'h4'])
                            if chapter_header:
                                chapter_no_span = chapter_header.find('span', class_=re.compile(r'LegChapterNo'))
                                chapter_title_span = chapter_header.find('span', class_=re.compile(r'LegChapterTitle'))
                                
                                if chapter_no_span or chapter_title_span:
                                    # Extract chapter number
                                    if chapter_no_span:
                                        chapter_no_clone = BeautifulSoup(str(chapter_no_span), 'xml')
                                        for restriction in chapter_no_clone.find_all('span', class_=re.compile(r'LegExtentRestriction|btr|bbl|bbr')):
                                            restriction.decompose()
                                        chapter_no_clone = _unwrap_formatting_tags(chapter_no_clone)
                                        chapter_number = chapter_no_clone.get_text(strip=True)
                                    else:
                                        chapter_number = chapter_id_full.split('-chapter-')[1] if '-chapter-' in chapter_id_full else str(len(chapters_in_part) + 1)
                                    
                                    # Extract chapter title
                                    if chapter_title_span:
                                        chapter_title_clone = BeautifulSoup(str(chapter_title_span), 'xml')
                                        for restriction in chapter_title_clone.find_all('span', class_=re.compile(r'LegExtentRestriction|btr|bbl|bbr')):
                                            restriction.decompose()
                                        chapter_title_clone = _unwrap_formatting_tags(chapter_title_clone)
                                        chapter_title = chapter_title_clone.get_text(strip=True)
                                    else:
                                        chapter_title = ''
                                    
                                    # Remove extent restrictions: E+W, standalone S (Scotland marker), U.K.
                                    # Use word boundary for S to avoid removing it from words like "Scotland"
                                    chapter_title = re.sub(r'\s*E\+W\s*', '', chapter_title)
                                    chapter_title = re.sub(r'\bS\b', '', chapter_title)  # Remove standalone S (word boundary)
                                    chapter_title = re.sub(r'\s*U\.K\.\s*', '', chapter_title)
                                    chapter_title = re.sub(r'\s+', ' ', chapter_title).strip()
                                    chapter_number = re.sub(r'\s+', ' ', chapter_number).strip()
                                    
                                    chapter_id = f"chapter-{len(chapters_in_part) + 1}"
                                    chapters_in_part.append({
                                        'id': chapter_id,
                                        'anchor_id': chapter_id_full,
                                        'element': chapter_header,
                                        'number': chapter_number,
                                        'title': chapter_title
                                    })
                
                # Also check h3/h4 headings for chapters (fallback)
                for heading in all_headings:
                    # Check if this heading is a chapter marker (h3 with LegChapter class or LegChapterTitle span)
                    is_chapter = False
                    chapter_title_span = None
                    
                    if 'LegChapter' in heading.get('class', []):
                        # h3 with LegChapter class - definitely a chapter
                        is_chapter = True
                        chapter_title_span = heading.find('span', class_=re.compile(r'LegChapterTitle'))
                    else:
                        # Check for LegChapterTitle or LegChapterNo spans
                        chapter_title_span = heading.find('span', class_=re.compile(r'LegChapterTitle|LegChapterNo'))
                        if chapter_title_span:
                            is_chapter = True
                    
                    if is_chapter and chapter_title_span:
                        # Check if this heading is within the current part's range and not already added
                        existing_chapter = None
                        for ch in chapters_in_part:
                            if ch['element'] == heading:
                                existing_chapter = ch
                                break
                        
                        if not existing_chapter:
                            # Check if heading comes after part anchor in document
                            try:
                                all_elems = list(soup.find_all(['a', 'h2', 'h3', 'h4']))
                                part_elem_idx = all_elems.index(part_anchor) if part_anchor in all_elems else -1
                                heading_elem_idx = all_elems.index(heading) if heading in all_elems else -1
                                
                                if part_elem_idx >= 0 and heading_elem_idx >= 0:
                                    is_in_range = False
                                    if next_part_anchor and next_part_anchor in all_elems:
                                        next_part_elem_idx = all_elems.index(next_part_anchor)
                                        if part_elem_idx < heading_elem_idx < next_part_elem_idx:
                                            is_in_range = True
                                    elif part_elem_idx < heading_elem_idx:
                                        is_in_range = True
                                    
                                    if is_in_range:
                                        chapter_title_clone = BeautifulSoup(str(chapter_title_span), 'xml')
                                        chapter_title_clone = _unwrap_formatting_tags(chapter_title_clone)
                                        chapter_title = chapter_title_clone.get_text(strip=True)
                                        # Remove extent restrictions: E+W, standalone S (Scotland marker), U.K.
                                        # Use word boundary for S to avoid removing it from words like "Scotland"
                                        chapter_title = re.sub(r'\s*E\+W\s*', '', chapter_title)
                                        chapter_title = re.sub(r'\bS\b', '', chapter_title)  # Remove standalone S (word boundary)
                                        chapter_title = re.sub(r'\s*U\.K\.\s*', '', chapter_title)
                                        chapter_title = re.sub(r'\s+', ' ', chapter_title).strip()
                                        
                                        chapter_no_span = heading.find('span', class_=re.compile(r'LegChapterNo'))
                                        if chapter_no_span:
                                            chapter_no_clone = BeautifulSoup(str(chapter_no_span), 'xml')
                                            for restriction in chapter_no_clone.find_all('span', class_=re.compile(r'LegExtentRestriction|btr|bbl|bbr')):
                                                restriction.decompose()
                                            chapter_no_clone = _unwrap_formatting_tags(chapter_no_clone)
                                            chapter_number = chapter_no_clone.get_text(strip=True)
                                        else:
                                            chapter_number = str(len(chapters_in_part) + 1)
                                        
                                        chapter_number = re.sub(r'\s+', ' ', chapter_number).strip()
                                        chapter_id = f"chapter-{len(chapters_in_part) + 1}"
                                        chapters_in_part.append({
                                            'id': chapter_id,
                                            'element': heading,
                                            'number': chapter_number,
                                            'title': chapter_title
                                        })
                            except:
                                pass
                
                print(f"Found {len(chapters_in_part)} chapters in part {part_id}")
                
                # Now process all sections and assign them to chapters or parts
                current_chapter_id = None
                
                # Build a list of all structural elements (chapters and sections) in order
                structural_elements = []
                
                # Add chapters
                for chapter_info in chapters_in_part:
                    structural_elements.append({
                        'type': 'chapter',
                        'data': chapter_info
                    })
                
                # Add sections
                for section_anchor in sections_in_part:
                    # Determine which chapter this section belongs to
                    section_chapter_id = None
                    
                    # Find the most recent chapter that comes before this section
                    for chapter_info in reversed(chapters_in_part):
                        # Check if chapter comes before section in document order
                        chapter_elem = chapter_info['element']
                        section_elem = section_anchor
                        
                        # Compare positions
                        all_elements = list(soup.find_all(['a', 'h3', 'h4']))
                        try:
                            chapter_idx = all_elements.index(chapter_elem)
                            section_idx = all_elements.index(section_elem)
                            if chapter_idx < section_idx:
                                # Check if there's no other chapter between this one and the section
                                has_intervening_chapter = False
                                for other_chapter in chapters_in_part:
                                    if other_chapter['id'] != chapter_info['id']:
                                        try:
                                            other_idx = all_elements.index(other_chapter['element'])
                                            if chapter_idx < other_idx < section_idx:
                                                has_intervening_chapter = True
                                                break
                                        except:
                                            pass
                                if not has_intervening_chapter:
                                    section_chapter_id = chapter_info['id']
                                    break
                        except:
                            pass
                    
                    structural_elements.append({
                        'type': 'section',
                        'anchor': section_anchor,
                        'chapter_id': section_chapter_id
                    })
                
                # Sort structural elements by their position in the document
                def get_element_position(elem_data):
                    if elem_data['type'] == 'chapter':
                        elem = elem_data['data']['element']
                    else:
                        elem = elem_data['anchor']
                    all_elements = list(soup.find_all(['a', 'h3', 'h4']))
                    try:
                        return all_elements.index(elem)
                    except:
                        return 999999
                
                structural_elements.sort(key=get_element_position)
                
                # Process all elements in order
                for elem_data in structural_elements:
                    if elem_data['type'] == 'chapter':
                        chapter_info = elem_data['data']
                        chapter_id = chapter_info['id']
                        if chapter_id not in part_structure['chapters']:
                            part_structure['chapters'][chapter_id] = {
                                'number': chapter_info.get('number', chapter_id.replace('chapter-', '')),
                                'title': chapter_info.get('title', ''),
                                'sections': {}
                            }
                    elif elem_data['type'] == 'section':
                        section_anchor = elem_data['anchor']
                        section_id = section_anchor.get('id')
                        section_chapter_id = elem_data['chapter_id']
                        
                        # Extract section hierarchy
                        section_entry = _extract_section_hierarchy(section_anchor, soup)
                        if section_entry:
                            if section_chapter_id and section_chapter_id in part_structure['chapters']:
                                # Add to chapter's sections
                                part_structure['chapters'][section_chapter_id]['sections'][section_id] = section_entry
                            else:
                                # Add directly to part's sections
                                part_structure['sections'][section_id] = section_entry
                
                # Clean up: remove empty chapters dict if no chapters
                if not part_structure.get('chapters', {}):
                    if 'chapters' in part_structure:
                        del part_structure['chapters']
                # Don't delete sections dict even if empty - we want to see if sections exist
                
                result['parts'][part_id] = part_structure
                print(f"Added part {part_id} with {len(part_structure.get('chapters', {}))} chapters and {len(part_structure.get('sections', {}))} direct sections")
            
            print(f"\nTotal parts processed: {len(result['parts'])}")
        else:
            # No parts - sections go directly at top level
            print("No parts found - placing sections directly at top level")
            result['sections'] = {}
            
            # Process all sections
            for section_anchor in all_section_anchors:
                section_id = section_anchor.get('id')
                section_entry = _extract_section_hierarchy(section_anchor, soup)
                if section_entry:
                    result['sections'][section_id] = section_entry
            
            print(f"\nTotal sections processed: {len(result['sections'])}")
        
        # Save to JSON file
        if output_file is None:
            part_dir = os.path.basename(os.path.dirname(part_file))
            base_name = os.path.splitext(os.path.basename(part_file))[0]
            output_file = os.path.join(os.path.dirname(part_file), f"{base_name}_legaldocML_hierarchy.json")
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=4, ensure_ascii=False)
        print(f"Saved LegalDocML hierarchy to {output_file}")
        
        return result
        
    except Exception as e:
        print(f"Error extracting LegalDocML hierarchy from {part_file}: {str(e)}")
        import traceback
        traceback.print_exc()
        return {}

if __name__ == "__main__":

    current_dir = os.path.dirname(os.path.abspath(__file__))
    print("Current directory:", os.getcwd())

    # Test the new hierarchy function with fixed title extraction
    part_file = current_dir + "/processed_acts/1964_81_part_1.xhtml"
    output_file = current_dir + "/output_for_json_builder/1964_81_part_1_sections_hierarchy.json"
    print("\n=== Testing extract_sections_with_hierarchy ===")
    result = extract_legaldocML_hierarchy(part_file, output_file)
    if result:
        print(f"\nSuccessfully extracted {len(result)} sections")
        # Show a sample section to verify titles
        if 'section-2' in result:
            print(f"\nSection 2 title: {result['section-2']['title']}")
    
