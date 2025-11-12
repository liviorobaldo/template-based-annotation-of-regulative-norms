## Deontic Annotation Automator

This directory contains the zero-shot annotation workflow and utilities to convert model output into the text format expected by the verifier tool.

### Components

- `zeroshot_opeai.py`: Sends a legislative JSON hierarchy and prompt template to an OpenAI chat model, writing parsed JSON and raw fallbacks.
- `prompt.txt`: Prompt template injected into every model call.
- `conersion_for_verifier.py`: Converts JSON annotations into the `annotation.txt` layout used by the verifier.
- `data/`: Example legislative JSON files as returned by the hierarchy extractor.
- `output/`: Default location for generated model responses and conversions.

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

### Running the Automator

#### 1. Generate annotations from JSON

```bash
python3 zeroshot_opeai.py data/1989_41_part_1_sections_hierarchy.json \
  --model gpt-4o-mini \
  --output output/parsed_1989-41_part1_4o.json \
  --raw-output output/raw_1989-41_part1_4o.txt \
  --print-raw
```

- The script loads `.env`, reads the prompt template, and submits the full JSON payload to the selected model.
- Parsed JSON is written to `--output`. If parsing fails, the raw response is saved (and always logged to `--raw-output` if specified).
- Use `run_cli([...])` from within Python/IDE to pass arguments programmatically.

#### 2. Convert parsed JSON for the verifier

```bash
python3 conersion_for_verifier.py output/parsed_1989-41_part1_4o.json \
  --output output/annotation_for_verifier_1989-41_part1_4o.txt \
  --print
```

- Produces blocks separated by `------------------------`, matching the verifier input format.
- Like the automator, `run_cli([...])` accepts argument lists when called from Python code.

### Files Produced

- `output/parsed_*.json`: Parsed JSON annotations suitable for post-processing.
- `output/raw_*.txt`: Raw model response after fence/quote cleanup, retained for debugging.
- `output/annotation_for_verifier_*.txt`: Text file ready to be copied into the verifier directory as `annotation.txt`.

### Notes

- Adjust model names and data paths as needed; the scripts do not hard-code a particular legislation file.
- The prompt template embeds the entire JSON document—ensure the target file is within the model’s context limits.
- If you delete or move outputs, update the README examples to match your new targets.
