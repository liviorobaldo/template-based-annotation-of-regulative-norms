import os
import re
from bs4 import BeautifulSoup
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def extract_year_from_title(title):
    """Extract year from the act title."""
    match = re.search(r'(\d{4})', title)
    return match.group(1) if match else None

def get_content_between_anchors(soup, start_anchor, end_anchor=None):
    """Extract content between two anchors."""
    if not start_anchor:
        return None
    
    # Start with the current anchor
    content = [str(start_anchor)]
    
    # Get all elements until the end anchor
    current = start_anchor
    while current.next_sibling:
        current = current.next_sibling
        if (isinstance(current, str) and current.strip()) or (hasattr(current, 'name') and current.name):
            if (end_anchor and current == end_anchor):
                break
            content.append(str(current))
    
    return ''.join(content)

def create_xhtml_file(head_str, content, output_file, title, year, chapter, long_title, enacting_text, enactment_date):
    """Create a complete XHTML file with the given content."""
    complete_doc = f'''<?xml version='1.0' encoding='UTF-8'?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en">
  <head>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>
    <title>{title}</title>
    <meta name="DC.Date.Modified" scheme="W3CDTF" content="2025-02-25"/>
    <meta name="DC.Date.Valid" scheme="W3CDTF" content="2025-02-24"/>
    <style type="text/css" media="screen, print">@import "../styles/legislation.css";@import "../styles/primarylegislation.css";</style>
  </head>
  <body>
    <div class="LegSnippet">
      <a name="content"/>
      <div class="DocContainer">
        <div class="LegClearFix LegPrelims">
          <h1 class="LegTitle">{title}</h1>
          <h1 class="LegNo">{year} CHAPTER {chapter}</h1>
          <p class="LegLongTitle">{long_title}</p>
          <p class="LegDateOfEnactment">{enactment_date}</p>
          <a class="LegAnchorID" id="Legislation-Preamble"/>
          <div class="LegEnactingText">
            <p class="LegText">{enacting_text}</p>
          </div>
        </div>
        {content}
      </div>
    </div>
  </body>
</html>'''
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(complete_doc)
    logging.info(f"Created file: {output_file}")
    return output_file

def count_sections_in_anchors(soup, start_anchor, end_anchor=None):
    """Count the number of sections between two anchors."""
    section_count = 0
    
    # Start with the current anchor
    current = start_anchor
    
    # Check if the current anchor is a section
    if current.get('id', '').startswith('section-'):
        section_count += 1
    
    # Count sections until reaching the end anchor
    while current.next_sibling:
        current = current.next_sibling
        if hasattr(current, 'name') and current.name == 'a' and current.get('id', '').startswith('section-'):
            section_count += 1
        if end_anchor and current == end_anchor:
            break
    
    return section_count

def group_anchors_by_section_count(anchors, soup, min_sections=10, max_sections=20):
    """Group anchors so each group contains between min and max sections."""
    groups = []
    current_group = []
    current_section_count = 0
    
    for i, anchor in enumerate(anchors):
        # If this is the last anchor, add it to the current group
        if i == len(anchors) - 1:
            current_group.append(anchor)
            groups.append(current_group)
            break
            
        # Count sections from this anchor to the next one
        next_anchor = anchors[i + 1]
        sections_in_anchor = count_sections_in_anchors(soup, anchor, next_anchor)
        
        # If adding this anchor would exceed max sections and the group isn't empty
        if current_section_count + sections_in_anchor > max_sections and current_group:
            groups.append(current_group)
            current_group = [anchor]
            current_section_count = sections_in_anchor
        else:
            current_group.append(anchor)
            current_section_count += sections_in_anchor
            
            # If we've reached at least min sections, check if we should close this group
            if current_section_count >= min_sections:
                # Look ahead to see if adding the next anchor would exceed max_sections
                if i < len(anchors) - 1:
                    next_anchor = anchors[i + 1]
                    next_sections = count_sections_in_anchors(soup, next_anchor)
                    if current_section_count + next_sections > max_sections:
                        groups.append(current_group)
                        current_group = []
                        current_section_count = 0
    
    # Add any remaining items to a group
    if current_group and current_group not in groups:
        groups.append(current_group)
    
    return groups

def split_legislation_file(input_file):
    """Split a legislation file into parts and return list of created files."""
    logging.info(f"Starting to process file: {input_file}")
    
    # Read the file
    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()
    logging.info(f"Successfully read file. Content length: {len(content)} characters")
    
    # Parse the XML
    logging.info("Attempting to parse XML...")
    soup = BeautifulSoup(content, 'xml')
    logging.info("Successfully parsed XML")
    
    # Extract title, year and chapter
    title = soup.find('title').text
    logging.info(f"Found act title: {title}")
    year = title.split()[2]  # Assuming format "Act Name Year"
    chapter = title.split('(')[1].split(')')[0].replace('c. ', '')  # Extract chapter number from (c. X)
    logging.info(f"Extracted year: {year}, chapter: {chapter}")
    
    # Extract long title and enacting text
    long_title = soup.find('p', class_='LegLongTitle').text if soup.find('p', class_='LegLongTitle') else ""
    enacting_text = soup.find('p', class_='LegText').text if soup.find('p', class_='LegText') else ""
    logging.info("Extracted long title and enacting text")
    
    # Extract enactment date
    enactment_date = ""
    enactment_date_elem = soup.find('p', class_='LegDateOfEnactment')
    if enactment_date_elem:
        enactment_date = enactment_date_elem.text
    logging.info(f"Extracted enactment date: {enactment_date}")
    
    created_files = []
    
    # Count total sections in the document
    section_anchors = soup.find_all('a', class_='LegAnchorID', id=lambda x: x and x.startswith('section-'))
    total_sections = len(section_anchors)
    logging.info(f"Total sections in document: {total_sections}")
    
    # Define the potential division types to check in order
    division_types = [
        ('part', 'part-'),
        ('chapter', 'chapter-'),
        ('regulation', 'regulation-'),
        ('rule', 'rule-')
    ]
    
    # Try each division type in order
    for division_name, division_prefix in division_types:
        division_anchors = soup.find_all('a', class_='LegAnchorID', id=lambda x: x and x.startswith(division_prefix))
        if division_anchors:
            logging.info(f"Found {len(division_anchors)} {division_name}s in the document")
            
            # Group the divisions based on section count
            division_groups = group_anchors_by_section_count(division_anchors, soup, 10, 20)
            
            logging.info(f"Created {len(division_groups)} groups of {division_name}s")
            
            # Process each group
            for i, group in enumerate(division_groups, start=1):
                # Get content from first to last division in group
                first_division = group[0]
                last_division = group[-1]
                
                # Count sections in this group
                section_count = 0
                for div in group:
                    if div == group[-1]:  # Last division in group
                        next_div = None
                        if i < len(division_groups):  # There's another group
                            next_div = division_groups[i][0]
                        section_count += count_sections_in_anchors(soup, div, next_div)
                    else:
                        next_div_idx = group.index(div) + 1
                        section_count += count_sections_in_anchors(soup, div, group[next_div_idx])
                
                logging.info(f"Group {i} contains {section_count} sections")
                
                # Find next division after the last one in this group
                next_division = None
                if i < len(division_groups):
                    next_division = division_groups[i][0]
                
                # Get content between anchors
                group_content = get_content_between_anchors(soup, first_division, next_division)
                
                # Create output file
                output_file = f"split_acts/{year}_{division_name}_group_{i}.xhtml"
                os.makedirs(os.path.dirname(output_file), exist_ok=True)
                
                # Create the file and add to list
                created_file = create_xhtml_file("", group_content, output_file, title, year, chapter, long_title, enacting_text, enactment_date)
                created_files.append(created_file)
            
            # If we found and processed a division type, return the results
            if created_files:
                return created_files
    
    # If no divisions found, split by sections
    if section_anchors:
        logging.info("No standard divisions found. Splitting by sections.")
        
        # Group sections into chunks of exactly 20 sections (or less for the last group)
        section_groups = [section_anchors[i:i+20] for i in range(0, len(section_anchors), 20)]
        
        for i, group in enumerate(section_groups, start=1):
            logging.info(f"Processing section group {i} ({len(group)} sections)")
            
            # Get content from first section to last section in group
            start_anchor = group[0]
            
            # Find the next section after the last one in this group
            end_anchor = None
            if i < len(section_groups):
                end_anchor = section_groups[i][0]
            
            # Get content between anchors
            section_content = get_content_between_anchors(soup, start_anchor, end_anchor)
            
            # Create output file
            output_file = f"split_acts/{year}_sections_group_{i}.xhtml"
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            
            # Create the file and add to list
            created_file = create_xhtml_file("", section_content, output_file, title, year, chapter, long_title, enacting_text, enactment_date)
            created_files.append(created_file)
    
    if not created_files:
        logging.warning("No content was split from the document")
    
    return created_files

if __name__ == "__main__":
    input_file = "processed_acts/2010_15.xhtml"
    split_legislation_file(input_file)