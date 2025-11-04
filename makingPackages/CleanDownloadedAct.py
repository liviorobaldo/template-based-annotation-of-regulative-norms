import os
import re
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from lxml import etree


def process_folder(input_folder,output_folder):
    folder = os.path.join(input_folder)
    if os.path.exists(folder):
        for file in os.listdir(folder):
            if file.lower().endswith(".xhtml"):
                input_file_path = os.path.join(folder, file)
                output_file_path = os.path.join(output_folder, file)
                process_file(input_file_path, output_file_path)
    else:
        print("The folder is empty or does not exist.")

def update_style_paths(head):
    if head is not None:
        # Find all style elements using BeautifulSoup's find_all
        for style in head.find_all('style'):
            if style.string:
                style.string = style.string.replace('@import "styles/', '@import "../styles/')

def remove_undesired_text(text):
    """Remove unwanted portions of the text and fix paths."""
    doctype = "\"http://www.w3.org/MarkUp/DTD/xhtml-rdfa-1.dtd\">"
    if doctype in text:
        text = text[text.index(doctype) + len(doctype):]
    
    while "/styles/" in text:
        index = text.index("/styles/")
        text = text[:index] + "styles/" + text[index + len("/styles/"):]
    
    return text

def remove_other_acts_amendments(element):
    """
    Check if element contains amendments to other acts.
    If so, return replacement text, else return None.
    """
    class_attr = element.get('class')
    if not class_attr:
        return None
    
    amendment_classes = [
        "LegClearFix LegP2Container LegAmend",
        "LegClearFix LegP3Container LegAmend",
        "LegClearFix LegP4Container LegAmend",
        "LegRHS LegP1TextC1Amend",
        "LegRHS LegP2TextC1Amend",
        "LegRHS LegP3TextC1Amend",
        "LegTabbedDefC1Amend LegUnorderedListC1Amend",
        "LegPartNo LegC1Amend",
        "LegSP1GroupTitleFirstC1Amend",
        "LegClearFix LegSP1Container LegAmend",
        "LegClearFix LegSP2Container LegAmend",
        "LegClearFix LegSP3Container LegAmend",
        "LegSP1GroupTitleC1Amend",
        "LegPartTitle LegC1Amend",
        "LegTabbedDefC3Amend LegUnorderedListC3Amend",
        "LegDS LegP1NoC3Amend",
        "LegDS LegRHS LegP1TextC3Amend",
        "LegSP1GroupTitleFirstC3Amend",
        "LegChapterNo LegC1Amend",
        "LegChapterTitle LegC1Amend",
        "LegRHS LegP2TextC3Amend",
        "LegClearFix LegSP4Container LegAmend",
        "LegTextC1Amend",
        "LegDS LegP1GroupTitleFirstC1Amend",
        "LegDS LegP1NoC1Amend"
    ]
    
    if class_attr in amendment_classes:
        return "TEXT REMOVED. MUST NOT BE ANNOTATED"
    
    return None

def remove_undesired_elements(soup, element):
    """Remove unwanted elements from the document."""
    # Check if we need to remove this element
    remove = False
    remove_subsequents = False
    
    if element.name == "span" and element.get('class') == "LegChangeDelimiter":
        remove = True
    
    if element.name == "a" and element.get('class') == "LegCommentaryLink":
        remove = True
    
    if element.name == "div" and element.get('class') == "LegAnnotations":
        remove = True
    
    if element.name == "h1" and element.get('class') == "LegSchedulesTitle":
        remove = True
        remove_subsequents = True
    
    # Check for amendments
    replace_text = remove_other_acts_amendments(element)
    
    if remove:
        # Find parent and index
        parent = element.parent
        if not parent:
            return
        
        # Find index
        siblings = list(parent.children)
        index = siblings.index(element)
        
        # Remove the element
        element.extract()
        
        # Remove subsequent elements if needed
        if remove_subsequents:
            for subsequent in list(parent.children)[index:]:
                subsequent.extract()
    
    elif replace_text:
        # Clear the element and replace with the text
        element.clear()
        element.string = replace_text
        element['style'] = "color:red;font-weight:bold"
    
    else:
        # Process child elements recursively
        for child in list(element.find_all(True, recursive=False)):
            remove_undesired_elements(soup, child)

def remove_span_including_only_text_must_be_removed(soup, element):
    """Remove spans containing only 'TEXT REMOVED' text."""
    if element.name != "span" or len(list(element.children)) != 1 or not element.string:
        # Process child elements recursively
        for child in list(element.find_all(True, recursive=False)):
            remove_span_including_only_text_must_be_removed(soup, child)
        return
    
    if element.string.strip() == "TEXT REMOVED. MUST NOT BE ANNOTATED":
        parent = element.parent
        if len(list(parent.children)) == 1:
            parent.clear()
            parent.string = "TEXT REMOVED. MUST NOT BE ANNOTATED"
            parent['style'] = "color:red;font-weight:bold"

def remove_double_removed_text_elements(soup, element):
    """Remove duplicate 'TEXT REMOVED' elements."""
    if element.get('style') == "color:red;font-weight:bold":
        parent = element.parent
        if not parent:
            return
        
        siblings = list(parent.find_all(True, recursive=False))
        index = siblings.index(element)
        
        if index > 0:
            # If previous element is also red, remove this one
            if siblings[index-1].get('style') == "color:red;font-weight:bold":
                element.extract()
            # Otherwise, if this element has class attribute, remove it
            elif element.get('class'):
                del element['class']
    else:
        # Process child elements recursively
        for child in list(element.find_all(True, recursive=False)):
            remove_double_removed_text_elements(soup, child)

def process_file(input_file_path, output_file_path):
    """Process a single XHTML file."""
    try:
        # Read input file
        with open(input_file_path, 'r', encoding='utf-8') as file:
            text = file.read()
        
        # Clean up the text
        text = remove_undesired_text(text)
        
        # Parse the document
        soup = BeautifulSoup(text, 'lxml-xml')
        
        # Add namespace declaration
        root = soup.find('html')
        if root:
            root['xmlns:xsi'] = "http://www.w3.org/2001/XMLSchema-instance"
        
        # Insert script code into the head element
        head = soup.find('head')
        if head:
            update_style_paths(head)
        
        
        # Process the document
        body = soup.find('body')
        if body:
            remove_undesired_elements(soup, body)
            remove_span_including_only_text_must_be_removed(soup, body)
            remove_double_removed_text_elements(soup, body)
            # Do it twice because merging might create spans with single text
            remove_span_including_only_text_must_be_removed(soup, body)
            remove_double_removed_text_elements(soup, body)
        
        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
        
        # Write to output file
        with open(output_file_path, 'w', encoding='utf-8') as file:
            file.write(str(soup))
        
        print(f"Processed {input_file_path} to {output_file_path}")
    
    except Exception as e:
        print(f"Error processing {input_file_path}: {type(e).__name__}: {e}")

def main():
    """Main function to process files."""
    import sys
    
    if len(sys.argv) == 3:
        process_file(sys.argv[1], sys.argv[2])
    else:
        # Fallback to default file paths
        input_folder = "./input/"
        output_folder = "./output_folder/"
        
        # Ensure output directory exists
        os.makedirs(output_folder, exist_ok=True)
        
        # Process all .xhtml files in the input folder
        if os.path.exists(input_folder):
            for filename in os.listdir(input_folder):
                if filename.lower().endswith('.xhtml'):
                    input_path = os.path.join(input_folder, filename)
                    output_path = os.path.join(output_folder, filename)
                    process_file(input_path, output_path)
        else:
            print("The input folder does not exist.")

if __name__ == "__main__":
    main()