from xml.etree.ElementTree import Element, SubElement

def convert_to_html(text,root):
    """
    Convert text to XML Element format, handling various structures like numbered points and lettered lists.
    
    Args:
        text (str): The text to convert
        
    Returns:
        Element: Root XML element containing the formatted text
    """
    if not text:
        return text

    #root = Element()
    numbered_points = []
    current_point = ''
    
    lines = text.split('.')
    i = 0
    while i < len(lines):
        if i < len(lines) - 1 and lines[i].strip() and lines[i][-1].isdigit():
            point = lines[i] + '.' + lines[i + 1]
            numbered_points.append(point.strip())
            i += 2
        elif i == 0:
            current_point = lines[i]
            i += 1
        else:
            if current_point:
                current_point += '.' + lines[i]
            else:
                current_point = lines[i]
            i += 1
    
    if current_point.strip():
        numbered_points.insert(0, current_point.strip())
    
    if len(numbered_points) <= 1:
        if any(f"({char})" in text.lower() for char in 'abcdefghijklmnopqrstuvwxyz'):
            if '(a)' in text:
                parts = text.split('(a)')
                main_text = parts[0].strip()
                list_content = '(a)' + parts[1]
                list_items = []
                current_item = ''
                
                for char in list_content:
                    current_item += char
                    if char == ',' or char == ';':
                        list_items.append(current_item.strip())
                        current_item = ''
                
                if current_item:
                    list_items.append(current_item.strip())
                
                p = SubElement(root, 'p')
                p.text = main_text
                ul = SubElement(root, 'ul')
                for item in list_items:
                    li = SubElement(ul, 'li')
                    li.text = item
                return root
        
        p = SubElement(root, 'p')
        p.text = text
        return root
    
    for point in numbered_points:
        if '(a)' in point.lower():
            parts = point.split('(a)')
            number_part = parts[0].strip()
            p = SubElement(root, 'p')
            p.text = number_part
            
            ul = SubElement(root, 'ul')
            remaining_text = '(a)' + parts[1]
            letter_items = []
            current_item = ''
            
            for i in range(len(remaining_text)):
                current_item += remaining_text[i]
                if i < len(remaining_text) - 2 and remaining_text[i+1] == '(' and remaining_text[i+2].isalpha():
                    letter_items.append(current_item.strip())
                    current_item = ''
            
            if current_item:
                letter_items.append(current_item.strip())
            
            for item in letter_items:
                li = SubElement(ul, 'li')
                li.text = item
        else:
            p = SubElement(root, 'p')
            p.text = point
    
    return root
# #Testing with all examples
# examples = [
#     "the protected characteristic is marriage or civil partnership, or it is a case of discrimination, harassment or victimisation— (a) that is prohibited by Part 3 (services and public functions), (b) that would be so prohibited but for an express exception.",
#     "I am testing this as well 1. How are you (a)Iam fine (b)I am good (c)I am great. 2. How are you (a)Iam fine (b)I am good (c)I am great.",
#     "A. This is the first point. B. This is the second point (a) with a subpoint (b) and another subpoint.",
#     "(1) This is the first point. (2) This is the second point (a) with a subpoint (b) and another subpoint. (3) This is the third point."
# ]

# # Print results for all examples
# for i, example in enumerate(examples):
#     print(f"\nExample {i+1}:")
#     print(convert_to_html(example))
