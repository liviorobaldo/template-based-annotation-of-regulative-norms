# Legislation Annotator Tool

This tool is designed to annotate legislative texts, specifically focusing on identifying and marking obligations, prohibitions, and permissions within the text.

## Features

- Annotate legislative texts for:
  - Obligations
  - Prohibitions
  - Permissions
- Two annotation styles:
  - Old style: Basic annotation without section of respective legialation section
  - New style: Advanced annotation with section selection and marking

## Getting Started

### Prerequisites

- Python 3.x
- Required Python packages:
  - requests
  - Other dependencies (to be listed)

### Installation

1. Clone the repository
2. Install required packages:
```bash
pip install -r requirements.txt 
or
python3 -m pip install -r requirements.txt
```

## Usage

The annotation process is initiated through `pipeline.py`. This script:

1. Accepts a legislation act URL
2. Downloads the act
3. Processes and converts the style according to the tool's requirements
4. Creates a deployment package with:
   - index.html (or index_with_selection.html for new style)
   - Required styles
   - Processed act files
   - Necessary scripts

### Running the Pipeline

```bash
python pipeline.py
or 
python3 pipeline.py

```

The script will:
1. Download the specified legislation act
2. Process the act for annotation
3. Create a deployment package
4. Generate a zip file containing all necessary files


## Project Structure

- `pipeline.py`: Main entry point for the annotation process
- `index.html`: Interface for annotation style
- `scripts/`: Contains JavaScript files for annotation functionality
- `styles/`: CSS files for styling the interface
- `processed_acts/`: Contains processed legislative texts
- `downloaded_acts/`: Contains downloaded legislative texts

## Output

The pipeline generates a `package.zip` file containing:
- The appropriate index.html file (based on selected style)
- Required style files
- Processed act files
- Necessary scripts

