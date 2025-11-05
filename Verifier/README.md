## Deontic Annotation Verifier

This tool verifies two sets of deontic sentence annotations. It:
- Identifies pairs that are exactly identical (ignoring spacing/case/punctuation)
- Identifies pairs that are reasonably equal (minor paraphrase)
- Identifies pairs with the same meaning but substantial paraphrase
- Flags pairs that annotate the same norm but with different meanings
- Lists annotations present only in one file or the other

Inputs are read from `annotation.txt` and `groundtruth.txt` in this directory. Results are written to `verification_results.json`. OpenAI requests/responses are logged to `openai_requests.jsonl` and `openai_responses.jsonl`.

## Getting Started

### Prerequisites

- Python 3.x
- Required Python packages:
  - rapidfuzz
  - python-dotenv
  - openai

### Installation

1. Clone the repository
2. Install required packages:
```bash
pip install -r requirements.txt
# or
python3 -m pip install -r requirements.txt
```

### Configure OpenAI

The verifier uses an LLM to categorize matched pairs. Set your OpenAI API key via a `.env` file in this directory or as an environment variable.

- Create a `.env` file next to `verifier.py` with:
```bash
OPENAI_API_KEY=your_api_key_here
```

- Alternatively, export it in your shell:
```bash
export OPENAI_API_KEY=your_api_key_here
```

### Prepare Inputs

Place your two annotation files in this directory with the following names:
- `annotation.txt`
- `groundtruth.txt`

Each annotation should be separated by a line containing only dashes (e.g., `-----`).

### Running the Pipeline

```bash
python verifier.py
# or
python3 verifier.py
```

### Outputs

- `verification_results.json`: Structured results grouped by category.
- `openai_requests.jsonl`: Batched request payloads sent to OpenAI (append-only log).
- `openai_responses.jsonl`: Raw JSON responses from OpenAI (append-only log).

### Notes

- This script expects `annotation.txt` and `groundtruth.txt` to be in the same directory as `verifier.py`. If you need custom paths, adapt the file paths in `__main__` inside `verifier.py`.
- Network access is required for LLM categorization. If the OpenAI response cannot be parsed for a batch, that batch is skipped and the script continues.

