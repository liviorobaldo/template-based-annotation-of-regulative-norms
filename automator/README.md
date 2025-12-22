## Deontic Annotation Automator

This directory contains the complete automation pipeline for legal annotation, supporting zero-shot, few-shot, and fine-tuning methods. All outputs are compatible with the verifier tool.

### Components

**Core Scripts:**
- `aggregate_all_annotations.py`: Combines all annotated CSV files from all acts into unified format
- `automation_pipeline.py`: Main orchestrator that runs zero-shot, few-shot, or fine-tuning methods
- `zeroshot_opeai.py`: Zero-shot annotation using OpenAI models
- `fewshot_automation.py`: Few-shot annotation with example annotations in prompt
- `finetuning_automation.py`: Fine-tuning preparation and execution
- `conersion_for_verifier.py`: Converts JSON annotations into verifier-compatible text format

**Configuration:**
- `prompt.txt`: Prompt template injected into every model call
- `data/`: Example legislative JSON files and unified annotations CSV
- `output/`: Default location for generated model responses and conversions

### Prerequisites

- Python 3.x
- Install dependencies using the local requirements file:
  ```bash
  pip install -r requirements.txt
  # or
  python3 -m pip install -r requirements.txt
  ```

### Configure OpenAI

Set your OpenAI API key via a `.env` file in this directory or as an environment variable.

- Create `.env`:
  ```bash
  OPENAI_API_KEY=your_api_key_here
  ```
- Or export it:
  ```bash
  export OPENAI_API_KEY=your_api_key_here
  ```

### Complete Workflow

#### Step 1: Aggregate All Annotations

First, combine all annotated CSV files from all acts into a unified format:

```bash
python3 aggregate_all_annotations.py \
  --root-dir ../Obligation_prohibition_picking_context \
  --output data/unified_annotations.csv
```

This creates a CSV with:
- `legislation_id`: Format like `1989_41_section-1` (act_year_chapter_section-id)
- `annotations`: JSON array of all annotations for that section

#### Step 2: Run Automation Pipeline

Run the complete pipeline using one of three methods:

**Zero-shot:**
```bash
python3 automation_pipeline.py data/unified_annotations.csv zeroshot \
  --hierarchy-dir ../Obligation_prohibition_picking_context \
  --output-dir output/zeroshot \
  --model gpt-4o \
  --format both
```

**Few-shot:**
```bash
python3 automation_pipeline.py data/unified_annotations.csv fewshot \
  --hierarchy-dir ../Obligation_prohibition_picking_context \
  --output-dir output/fewshot \
  --model gpt-4o \
  --num-examples 3 \
  --format both
```

**Fine-tuning:**
```bash
# Step 2a: Prepare training data
python3 finetuning_automation.py prepare data/unified_annotations.csv \
  --hierarchy-dir ../Obligation_prohibition_picking_context \
  --output data/training_data.jsonl

# Step 2b: Upload training file
python3 finetuning_automation.py upload data/training_data.jsonl

# Step 2c: Create fine-tuning job (use file_id from upload)
python3 finetuning_automation.py create file-abc123 \
  --model gpt-4o-mini \
  --suffix legal-annotator

# Step 2d: Check job status
python3 finetuning_automation.py status ftjob-xyz789

# Step 2e: Run annotation with fine-tuned model
python3 automation_pipeline.py data/unified_annotations.csv finetuning \
  --hierarchy-dir ../Obligation_prohibition_picking_context \
  --output-dir output/finetuning \
  --model ft:gpt-4o-mini:org:legal-annotator:abc123 \
  --format both
```

#### Step 3: Verify Results

The pipeline automatically generates verifier-compatible text files:
- `output/{method}_annotations.txt`: Ready for verifier
- `output/{method}_annotations.json`: JSON format for processing
- `output/{method}_breakdown.json`: Per-legislation breakdown

Copy the text file to the Verifier directory:
```bash
cp output/zeroshot/zeroshot_annotations.txt ../Verifier/annotation.txt
cd ../Verifier
python3 verifier.py
```

### Individual Script Usage

#### Zero-shot (standalone)

```bash
python3 zeroshot_opeai.py data/1989_41_part_1_sections_hierarchy.json \
  --model gpt-4o-mini \
  --output output/parsed_1989-41_part1_4o.json \
  --raw-output output/raw_1989-41_part1_4o.txt
```

#### Few-shot (standalone)

```bash
python3 fewshot_automation.py data/1989_41_part_1_sections_hierarchy.json \
  data/unified_annotations.csv \
  --model gpt-4o \
  --num-examples 3 \
  --output output/fewshot_result.json
```

#### Convert to Verifier Format

```bash
python3 conersion_for_verifier.py output/parsed_1989-41_part1_4o.json \
  --output output/annotation_for_verifier_1989-41_part1_4o.txt
```

### Output Files

**Pipeline Outputs:**
- `output/{method}_annotations.json`: All annotations in JSON format
- `output/{method}_annotations.txt`: Verifier-compatible text format
- `output/{method}_breakdown.json`: Per-legislation section breakdown

**Individual Script Outputs:**
- `output/parsed_*.json`: Parsed JSON annotations
- `output/raw_*.txt`: Raw model response (for debugging)
- `output/annotation_for_verifier_*.txt`: Verifier-compatible text

### Data Format

**Unified Annotations CSV:**
- `legislation_id`: Format `{year}_{chapter}_{section-id}` (e.g., `1989_41_section-1`)
- `annotations`: JSON array of annotation objects

**Annotation Object Structure:**
```json
{
  "main_section": "https://www.legislation.gov.uk/ukpga/1989/41/section/1",
  "type": "OBLIGATORY" | "PROHIBITED" | "PERMITTED",
  "for": "actor(s) described in the norm",
  "to": "action required/forbidden/permitted",
  "conditions": [
    {
      "type": "WHEN/IF/WHERE" | "ONLY IF" | "BEFORE" | "AFTER" | "SUBJECT TO" | "UNLESS",
      "text": "condition text",
      "section": "section URL or null"
    }
  ]
}
```

### Notes

- The pipeline automatically finds hierarchy JSON files by matching act identifiers
- All methods output in verifier-compatible format automatically
- Fine-tuning requires OpenAI API access and can take several hours
- Adjust model names, paths, and parameters as needed for your use case
- The prompt template embeds the entire JSON document—ensure files are within model context limits
