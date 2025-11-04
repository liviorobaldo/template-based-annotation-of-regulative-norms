import requests
import CleanDownloadedAct
from LegislationHandler import LegislationParser
import util
import shutil
import os
from split_legislation import split_legislation_file

from bs4 import BeautifulSoup
import re

def all_sections_are_empty(xhtml: str) -> bool:
    soup = BeautifulSoup(xhtml, "lxml")
    empty = True

    for h4 in soup.find_all("h4"):
        span = h4.find("span", class_="LegDS LegP1No")
        if span:
            full_text = h4.get_text(strip=True)
            section_id = span.get_text(strip=True)
            remainder = full_text.replace(section_id, "", 1).strip()

            # Check if the remainder is only dots, spaces, or bullet variants
            if not re.fullmatch(r"[.\s·•\u2022\u00b7·]+", remainder):
                empty = False
                break

    return empty

def download_legislation_act_as_xhtml(url, act_id, folder="downloaded_acts"):
    # Perform the GET request.
    response = requests.get(url)
    response.raise_for_status()  # Raise an error for bad status codes

    act_id_output = act_id.replace("/", "_")
    # Create the folder if it doesn't exist
    os.makedirs(folder, exist_ok=True)
    output_file = f"{folder}/{act_id_output}.xhtml"
    # Save the content to the output file as a .xhtml file.
    with open(output_file, 'wb') as f:
        f.write(response.content)
    
    print(f"Saved legislation act to: {output_file}")
    return output_file

def create_package_for_part(part_file, part_number, act_id_output, select_the_annotator_type, packages_dir):
    # Create package directory for this part
    package_dir = f'{packages_dir}/{act_id_output}_part_{part_number}'
    os.makedirs(package_dir, exist_ok=True)

    # Copy required files and folders
    shutil.copy('index.html', f'{package_dir}/index.html')
    
    # Create acts directory and copy the part file
    os.makedirs(f'{package_dir}/acts', exist_ok=True)
    shutil.copy(part_file, f'{package_dir}/acts/{act_id_output}.xhtml')
    output_file_name = f'{act_id_output}_part_{part_number}.txt'
    util.update_export_filename(output_file_name)
    # Copy styles and scripts
    shutil.copytree('styles', f'{package_dir}/styles', dirs_exist_ok=True)
    shutil.copytree('scripts', f'{package_dir}/scripts', dirs_exist_ok=True)

    # Create zip archive of package folder
    shutil.make_archive(f'{packages_dir}/{act_id_output}_part_{part_number}', 'zip', package_dir)
    print(f"Created package for part {part_number}: {act_id_output}_part_{part_number}.zip")

def process_legislation_act(url, act_id, select_the_annotator_type, packages_dir):
    print(f"\nProcessing legislation: {act_id}")
    print("Downloading from:", url)
    
    act_id_output = act_id.replace("/", "_")
    downloaded_file = download_legislation_act_as_xhtml(url, act_id)
    CleanDownloadedAct.process_file(f"./downloaded_acts/{act_id_output}.xhtml",f"./processed_acts/{act_id_output}.xhtml")
    # Clean and process the downloaded act
    #CleanDownloadedAct.process_folder("downloaded_acts", "processed_acts")
    
    # Get the processed file path
    processed_file = f"./processed_acts/{act_id_output}.xhtml"
    
    # Split the legislation into parts
    print("Splitting legislation into parts...")
    split_files = split_legislation_file(processed_file)
    
    if not split_files:
        print("Error: No parts were created from the legislation file")
        return
    
    print(f"Successfully split legislation into {len(split_files)} parts")
    
    util.update_iframe_src(f"acts/{act_id_output}.xhtml", "index.html")
    
    # Create packages for each part
    for part_number, part_file in enumerate(split_files, start=1):
        print(f"Creating package for part {part_number}...")
        create_package_for_part(part_file, part_number, act_id_output, select_the_annotator_type, packages_dir)

    print(f"Completed processing {act_id}")

if __name__ == "__main__":
    select_the_annotator_type = "old"
    
    # List of legislation to process
    
    legislation_list = [
        {
            'act_id': '1989/41',
            'url': 'https://www.legislation.gov.uk/ukpga/1989/41/data.xht?view=snippet&wrap=true'
        },
        {
            'act_id': '1964/81',
            'url': 'https://www.legislation.gov.uk/ukpga/1964/81/data.xht?view=snippet&wrap=true'
        },
        {
            'act_id': '2021/17',
            'url': 'https://www.legislation.gov.uk/ukpga/2021/17/data.xht?view=snippet&wrap=true'
        },
        {
            'act_id': '2020/24',
            'url': 'https://www.legislation.gov.uk/ukpga/2020/24/data.xht?view=snippet&wrap=true'
        },
        {
            'act_id': '2019/18',
            'url': 'https://www.legislation.gov.uk/ukpga/2019/18/data.xht?view=snippet&wrap=true'
        },
        {
            'act_id': '2020/24',
            'url': 'https://www.legislation.gov.uk/ukpga/2020/24/data.xht?view=snippet&wrap=true'
        },
        {
            'act_id': '2018/16',
            'url': 'https://www.legislation.gov.uk/ukpga/2018/16/data.xht?view=snippet&wrap=true'
        },
        {
            'act_id': '2016/25',
            'url': 'https://www.legislation.gov.uk/ukpga/2016/25/data.xht?view=snippet&wrap=true'
        },
        {
            'act_id': '2015/9',
            'url': 'https://www.legislation.gov.uk/ukpga/2015/9/data.xht?view=snippet&wrap=true'
        },
        {
            'act_id': '2014/6',
            'url': 'https://www.legislation.gov.uk/ukpga/2014/6/data.xht?view=snippet&wrap=true'
        }
        
    ]
    
    #Create packages directory
    packages_dir = "packages"
    os.makedirs(packages_dir, exist_ok=True)
    
    # Process each legislation
    for legislation in legislation_list:
        process_legislation_act(
            legislation['url'],
            legislation['act_id'],
            select_the_annotator_type,
            packages_dir
        )

    print("\nPipeline completed successfully!")
    print(f"All packages have been created in the '{packages_dir}' directory.") 