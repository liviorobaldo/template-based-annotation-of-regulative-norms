import requests
import xml.etree.ElementTree as ET
import os
import json
class LegislationParser:
    """
    A parser for UK legislation that extracts titles, terms, and sections from legislation.gov.uk XML data.
    """

    def __init__(self, url, is_section=False):
        """
        Initializes the parser with the legislation URL and determines the appropriate XML structure.

        Args:
            url (str): URL to fetch legislation XML.
            is_section (bool): Whether a specific section ID is being fetched.
        """
        self.debug = False  # Toggle debugging output

        # Extract section ID and base URL
        self.element_id, base_url = self.getTheSectionIdAndBaseUrl(url)
        self.url = base_url + "/data.akn"

        # Ensure secure URL
        if not self.url.startswith("https:"):
            self.url = self.url.replace("http", "https")

        # Define namespaces
        self.namespace = {'akn': 'http://docs.oasis-open.org/legaldocml/ns/akn/3.0'}

        # Load XML tree
        self.tree = self._load_legislation()

    def _load_legislation(self):
        """Fetches and parses the XML from the given URL."""
        try:
            response = requests.get(self.url)
            if response.status_code == 200:
                return ET.ElementTree(ET.fromstring(response.content))
            else:
                raise Exception(f"Failed to load legislation data: {response.status_code}")
        except ET.ParseError:
            raise Exception("Error parsing the XML document")
        except Exception as e:
            raise Exception(f"An unexpected error occurred: {e}")

    def get_legislation_title(self):
        """
        Fetches the title of the legislation from the XML document.

        Returns:
            str: The title of the legislation or an error message.
        """
        try:
            root = self.tree.getroot()
            
            # Check multiple possible title locations
            title_elements = [
                root.find(".//akn:longTitle", self.namespace),  # For Acts (ukpga)
                root.find(".//akn:shortTitle", self.namespace),  # Alternative title location
                root.find(".//akn:docTitle", self.namespace),  # Common title tag
                root.find(".//akn:title", self.namespace),  # General title
                root.find(".//akn:name", self.namespace),  # Used in some cases
                root.find(".//akn:heading", self.namespace)  # Used in UKSI documents
            ]
            
            for title_element in title_elements:
                if title_element is not None and title_element.text:
                    return title_element.text.strip()

            return "Title not found in the XML document"
        except Exception as e:
            return f"An error occurred while extracting title: {e}"

    def get_title_tree(self, file_name="title_tree.json"):
        """
        Constructs a hierarchical representation of the legislation's structure,
        including sections, parts, and subparts, handling intermediate containers.
        
        Returns:
            list: A JSON-like list representing the hierarchy of sections, parts, and subparts.
        """
        root = self.tree.getroot()
        
        # Define the structural elements we want to capture
        structural_tags = [
            f"{{{self.namespace['akn']}}}part",
            f"{{{self.namespace['akn']}}}chapter", 
            f"{{{self.namespace['akn']}}}section",
            f"{{{self.namespace['akn']}}}article",
            f"{{{self.namespace['akn']}}}regulation"
        ]
        
        def get_title(element):
            """Extract the title from an element."""
            title = element.find(".//akn:heading", self.namespace) or element.find(".//akn:title", self.namespace)
            return title.text.strip() if title is not None and title.text else "Untitled"
        
        def process_element(element):
            """
            Recursively process an element and its children to build the hierarchy.
            """
            # Initialize the current element's data
            result = {
                "title": get_title(element),
                "id": element.attrib.get("eId", "unknown"),
                "children": []
            }
            
            # Process all children (including those in hcontainers)
            for child in element:
                # If child is a structural element, process it directly
                if child.tag in structural_tags:
                    result["children"].append(process_element(child))
                # If child is an hcontainer or other container, look for structural elements inside it
                else:
                    for descendant in child.findall(".//*", self.namespace):
                        if descendant.tag in structural_tags:
                            # Check if this descendant is a direct child of the container
                            # and not nested inside another structural element
                            is_direct = True
                            parent = descendant.getparent() if hasattr(descendant, 'getparent') else None
                            
                            while parent and parent != child:
                                if parent.tag in structural_tags:
                                    is_direct = False
                                    break
                                parent = parent.getparent() if hasattr(parent, 'getparent') else None
                            
                            if is_direct:
                                result["children"].append(process_element(descendant))
            
            return result
        
        # Find all top-level structural elements in the document
        top_level_elements = []
        
        # Using XPath to find elements that are not contained within other structural elements
        for tag in ["part", "chapter", "section", "article", "regulation"]:
            xpath = f".//akn:{tag}"
            for element in root.findall(xpath, self.namespace):
                # Check if this element is inside another structural element
                is_top_level = True
                
                if hasattr(element, 'getparent'):  # Using lxml
                    parent = element.getparent()
                    while parent is not None and parent != root:
                        if parent.tag in structural_tags:
                            is_top_level = False
                            break
                        parent = parent.getparent()
                else:  # Using standard ElementTree
                    # Alternative approach for standard ElementTree without getparent()
                    for struct_tag in structural_tags:
                        # Find all elements of this structural type
                        for potential_parent in root.findall(f".//{struct_tag}", self.namespace):
                            # If not the current element itself and contains our element
                            if potential_parent != element and potential_parent.find(f".//{element.tag}[@eId='{element.attrib.get('eId', '')}']", self.namespace) is not None:
                                is_top_level = False
                                break
                        if not is_top_level:
                            break
                
                if is_top_level:
                    top_level_elements.append(process_element(element))
        
        # Write the result to a file
        with open(file_name, "w", encoding="utf-8") as f:
            json.dump(top_level_elements, f, indent=4)
        
        return top_level_elements
    
    
    def get_sections(self):
        """
        Retrieves all sections or regulations from the XML document.

        Returns:
            list: A list of dictionaries containing section ID and text.
        """
        root = self.tree.getroot()

        # Filter out <akn:part> elements that contain <akn:section> elements
        part_elements = root.findall(".//akn:part", self.namespace)
        valid_parts = [part for part in part_elements if not self._contains_section(part)]

        chapter_elements = root.findall(".//akn:chapter", self.namespace)
        valid_chapters = [chapter for chapter in chapter_elements if not self._contains_section(chapter)]


        # Collect section-like elements
        section_elements = (
            root.findall(".//akn:section", self.namespace) +  # UK Acts (ukpga)
            root.findall(".//akn:regulation", self.namespace) +  # UK Statutory Instruments (uksi)
            valid_parts +  # Include only valid <akn:part> elements
            valid_chapters +  # Some UKSI use <akn:chapter>
            root.findall(".//akn:article", self.namespace)  # Some laws use <akn:article>
        )

        sections = []
        for section in section_elements:
            section_id = section.attrib.get("eId", "unknown")
            section_text = self._extract_text(section)
            sections.append({"id": section_id, "text": section_text})

        return sections

    def _contains_section(self, element):
        """
        Checks if an XML element contains any <akn:section> elements at any level of nesting.
        
        Args:
            element (xml.etree.ElementTree.Element): The XML element to check.
        
        Returns:
            bool: True if the element contains <akn:section> elements, False otherwise.
        """
        # Define the section tag with namespace
        section_tag = f"{{{self.namespace['akn']}}}section"
        
        # Check if this element is a section
        if element.tag == section_tag:
            return True
        
        # Recursively check all children
        for child in element:
            if self._contains_section(child):
                return True
        
        return False

    def save_all_sections_to_files(self, output_dir="legislation_sections"):
        """
        Saves all sections or regulations in the legislation to individual text files.

        Args:
            output_dir (str): Directory where section text files will be saved.
        """
        os.makedirs(output_dir, exist_ok=True)

        sections = self.get_sections()
        if not sections:
            print("No sections or regulations found.")
            return

        for section in sections:
            file_path = os.path.join(output_dir, f"{section['id']}.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(section['text'])
            print(f"Saved: {file_path}")

    def _extract_text(self, element):
        """Extracts all text content from an XML element and its children."""
        texts = []

        def process_node(node):
            if node.text and node.text.strip():
                texts.append(node.text.strip())
            for child in node:
                process_node(child)
                if child.tail and child.tail.strip():
                    texts.append(child.tail.strip())

        process_node(element)
        return " ".join(texts)

    def getTheSectionIdAndBaseUrl(self, url):
        """
        Extracts the base URL and section ID from a given UK legislation URL.

        Args:
            url (str): Legislation URL.

        Returns:
            tuple: (section ID, base URL)
        """
        url_parts = url.split('/')
        if 'id' in url_parts:
            url_parts.remove('id')

        section_idx = -1
        for i, part in enumerate(url_parts):
            if part.lower() in ['section', 'regulation', 'part', 'chapter', 'article']:
                section_idx = i
                break

        if section_idx == -1:
            return "", '/'.join(url_parts)

        section_id = '-'.join(url_parts[section_idx:]).lower()
        base_url = '/'.join(url_parts[:section_idx])
        return section_id, base_url

    def set_debug(self, debug_mode):
        """Enables or disables debug output."""
        self.debug = debug_mode


# Example usage:
if __name__ == "__main__":
    url_act = "https://www.legislation.gov.uk/ukpga/2018/16"
    url_act = "https://www.legislation.gov.uk/ukpga/2022/32"
    url_regulation = "https://www.legislation.gov.uk/uksi/2013/435"

    # Parse UK Act
    parser_act = LegislationParser(url_act, False)
    print("Act Title:", parser_act.get_legislation_title())
    parser_act.get_title_tree("2022_32_section_tree.json")
    parser_act.save_all_sections_to_files("data/2022/32")

    '''
    # Parse UK Statutory Instrument (Regulation)
    parser_regulation = LegislationParser(url_regulation, False)
    print("Regulation Title:", parser_regulation.get_legislation_title())
    parser_regulation.save_all_sections_to_files("data/legislation/uksi/2013/435")
    '''