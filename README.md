# typify-cli

`typify-cli` is the standalone inference engine and CLI used by the VS Code extension. It can also be used independently for research, experimentation, batch analysis, and integration into downstream tools.

## Installation

Requires **Python 3.11 or higher**.

```bash
pip install typify-cli
```

### Dependencies

The following packages are installed automatically by the above command: `tantivy`, `rich`, `gdown`, and `requests`.

---

## How Typify Works

The analysis pipeline consists of several stages:

1. **Dependency graph construction** - builds a project-wide import graph and handles circular imports through fixpoint iteration.

2. **Usage-driven inference** - infers types from assignments, operators, method calls, and usage patterns. Types accumulate monotonically over time.

3. **Propagation passes** - re-applies inferred call-site information across multiple rounds, resolving increasingly deep call chains.

4. **Context-matching retrieval** - queries a search index of annotated Python code for unresolved slots.

5. **Type4Py integration** - uses neural predictions for remaining unresolved cases.

---

## Usage

### Inference

```bash
Usage: typify infer [PROJECT-PATH] [OUTPUT-PATH] [OPTIONS]

Arguments:
  PROJECT-PATH    Path to the project directory
  OUTPUT-PATH     Output directory to write inferred types into

Options:
  --config PATH   Path to a config file to configure inference
```

### Output Structure

The output directory contains:

```text
types/           # JSON type outputs per file
index.json       # Source-to-output mapping
config.json      # Analyzer configuration
context-index/   # Retrieval index
```

<img src="media/screenshots/cli.webp" alt="typify-cli infer">

The generated output is designed to be consumed directly by the Typify VS Code extension.

Subsequent runs are incremental: only changed files are reprocessed by retrieval and Type4Py passes.

See [schema.md](schema.md) for the full output format.

---

## Configuration

On first run, Typify writes a default `config.json`:

```json
{
    "context-retrieval": true,
    "context-index-download": "<gdrive-url>",
    "retrieval-top-k": 5,
    "type4py": true,
    "type4py-api-url": "https://type4py.ali-aman.ca/api/predict?tc=0",
    "augment-context": false,
    "propagation-passes": 3,
    "symbolic-depth": 3
}
```

| Field                    | Description                         |
| ------------------------ | ----------------------------------- |
| `context-retrieval`      | Enable retrieval-based inference    |
| `context-index-download` | Retrieval index download URL        |
| `retrieval-top-k`        | Number of retrieved candidates      |
| `type4py`                | Enable Type4Py integration          |
| `type4py-api-url`        | Type4Py API endpoint                |
| `augment-context`        | Experimental retrieval augmentation |
| `propagation-passes`     | Number of propagation rounds        |
| `symbolic-depth`         | Symbolic execution recursion depth  |

For more details, refer to the [ICPC 2026 paper](https://doi.org/10.1145/3794763.3794825).

---

## Building a Custom Retrieval Index

Researchers can build their own retrieval indexes using:

```bash
Usage: typify build [DATASET-PATH] [INDEX-PATH] [OPTIONS]

Arguments:
  DATASET-PATH    Path to the dataset directory
  INDEX-PATH      Output directory to write the retrieval index into

Options:
  --workers N     Number of parallel workers to use during index construction
```

Supported datasets include:

- ManyTypes4Py
- Typilus
- Any annotated Python corpus

This enables experimentation with domain-specific retrieval corpora.

---

## Batch Inference and Evaluation

For large-scale analysis across entire datasets, such as benchmarking Typify against a corpus of Python projects, `typify-cli` provides three commands that together form an end-to-end evaluation pipeline: ground-truth extraction, batch inference, and result comparison.

### `typify gt` - Ground-Truth Extraction

Extracts type annotations from an already-annotated dataset, producing a JSON file that serves as the reference ground truth for evaluation. Run this first on any dataset that contains existing annotations.

```bash
Usage: typify gt [DATASET-PATH] [OUTPUT-PATH]

Arguments:
  DATASET-PATH    Path to the dataset directory
  OUTPUT-PATH     Output JSON file to write extracted annotations into
```

---

### `typify dataset` - Batch Inference

Runs Typify's inference engine over an entire dataset directory, processing each project and writing predicted types to a JSON output file.

```bash
Usage: typify dataset [DATASET-PATH] [OUTPUT-PATH] [OPTIONS]

Arguments:
  DATASET-PATH    Path to the dataset directory
  OUTPUT-PATH     Output JSON file for inferred type predictions

Options:
  --config PATH   Path to a config file to configure inference
```

---

### `typify eval` - Evaluation

Compares Typify's predictions against the ground truth produced by `typify gt`, reporting accuracy using both exact-match and base-type matching.

```bash
Usage: typify eval [GT-PATH] [TOOL-PATH]

Arguments:
  GT-PATH      Ground-truth JSON file produced by typify gt
  TOOL-PATH    Inference output JSON file produced by typify dataset
```

---