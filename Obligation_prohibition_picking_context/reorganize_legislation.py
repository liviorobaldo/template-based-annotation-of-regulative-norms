import os
import re
import shutil

def extract_section_number(filename):
    """
    Extract the section number from a filename.
    
    Args:
        filename (str): The filename (e.g., "section-1.txt", "part-7.txt")
            
    Returns:
        int or None: The section number if found, None otherwise
    """
    # For section files like "section-1.txt", "section-100.txt"
    section_match = re.search(r'section-(\d+[A-Za-z]?)', filename)
    if section_match:
        # Handle cases like "section-124A.txt"
        section_num = section_match.group(1)
        # Remove any non-numeric characters for sorting
        numeric_part = re.sub(r'[^0-9]', '', section_num)
        return int(numeric_part) if numeric_part else None
    
    return None

def read_file(file_path):
    """Read a file and return its content."""
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()

def contains_section_number(text, section_number):
    """
    Check if the text contains a reference to the section number.
    
    Args:
        text (str): The text to search in
        section_number (int): The section number to look for
        
    Returns:
        bool: True if the section number is found, False otherwise
    """
    # Look for patterns like "100 Application of this Part" or "Section 100"
    patterns = [
        rf'\b{section_number}\b',  # The number by itself
        rf'[Ss]ection\s+{section_number}\b',  # "Section X"
    ]
    
    for pattern in patterns:
        if re.search(pattern, text):
            return True
    
    return False

def main():
    # Paths
    source_dir = 'data/2010/15'
    target_dir = 'data/2010_new'
    
    # Create target directory
    os.makedirs(target_dir, exist_ok=True)
    
    # Get all section files
    section_files = []
    section_numbers = set()
    
    for filename in os.listdir(source_dir):
        if filename.startswith('section-') and filename.endswith('.txt'):
            file_path = os.path.join(source_dir, filename)
            section_number = extract_section_number(filename)
            
            if section_number:
                section_numbers.add(section_number)
                section_files.append({
                    'path': file_path,
                    'filename': filename,
                    'number': section_number
                })
    
    # Copy all section files to the target directory
    for section_file in section_files:
        source_path = section_file['path']
        target_path = os.path.join(target_dir, section_file['filename'])
        shutil.copy2(source_path, target_path)
        print(f"Copied: {section_file['filename']}")
    
    # Copy all schedule files
    schedule_files = []
    for filename in os.listdir(source_dir):
        if filename.startswith('schedule-') and filename.endswith('.txt'):
            file_path = os.path.join(source_dir, filename)
            schedule_files.append({
                'path': file_path,
                'filename': filename
            })
    
    # Copy all schedule files to the target directory
    for schedule_file in schedule_files:
        source_path = schedule_file['path']
        target_path = os.path.join(target_dir, schedule_file['filename'])
        shutil.copy2(source_path, target_path)
        print(f"Copied: {schedule_file['filename']}")
    
    # Process other files (parts, chapters, etc.)
    for filename in os.listdir(source_dir):
        if (not filename.startswith('section-') and 
            not filename.startswith('schedule-') and 
            filename.endswith('.txt')):
            
            file_path = os.path.join(source_dir, filename)
            file_content = read_file(file_path)
            
            # Check if this file contains content that's already in section files
            contains_known_section = False
            for section_number in section_numbers:
                if contains_section_number(file_content, section_number):
                    contains_known_section = True
                    print(f"Skipping {filename} - contains section {section_number}")
                    break
            
            # If it doesn't contain any known sections, copy it
            if not contains_known_section:
                target_path = os.path.join(target_dir, filename)
                shutil.copy2(file_path, target_path)
                print(f"Copied: {filename}")
    
    print(f"\nReorganization complete. Files saved to {target_dir}")
    print(f"Total section files: {len(section_files)}")
    print(f"Total section numbers: {len(section_numbers)}")

if __name__ == "__main__":
    main()
