import json
import argparse
import sys
import zipfile
from pathlib import Path

import gdown
from rich.progress import Progress, SpinnerColumn, TextColumn, track

from .pipeline import collect_entries
from .usage.symbol_table import Registry
from .usage.collector import collect
from .usage.infer import infer_file
from .retrieval.build import build_index
from .retrieval.query import TypeRetriever
from .retrieval.retrieve_file import retrieve_file
from .type4py.infer_file import infer_file as type4py_infer_file

_DEFAULT_CONFIG = {
    "context-retrieval": True,
    "context-index-download": "https://drive.google.com/file/d/1rzxFqKOo-A4mlctp6bzekky_80EIS-Xa/view?usp=sharing",
    "retrieval-top-k": 5,
    "type4py": True,
    "type4py-api-url": "https://type4py.ali-aman.ca/api/predict?tc=0",
    "augment-context": False,
}


def _maybe_download_index(output_dir: Path, config: dict) -> None:
    """Download and extract the context index if retrieval is on and index is absent."""
    if not config.get("context-retrieval", _DEFAULT_CONFIG["context-retrieval"]):
        return
    index_dir = output_dir / "context-index"
    if index_dir.is_dir():
        return
    url = config.get("context-index-download", _DEFAULT_CONFIG["context-index-download"])
    if not url:
        return

    zip_path = output_dir / "context-index.zip"
    with Progress(SpinnerColumn(), TextColumn("{task.description}"), transient=False) as progress:
        task = progress.add_task("Downloading context index...", total=None)
        gdown.download(url=url, output=str(zip_path), quiet=True)
        progress.update(task, description="Extracting context index...  ")
        with zipfile.ZipFile(zip_path, "r") as zf:
            index_dir.mkdir(parents=True, exist_ok=True)
            zf.extractall(index_dir)
        progress.update(task, description="Context index ready.         ")
    zip_path.unlink(missing_ok=True)


def _load_config(output_dir: Path) -> dict:
    config_path = output_dir / "config.json"
    if config_path.exists():
        with config_path.open(encoding="utf-8") as f:
            return json.load(f)
    config_path.write_text(
        json.dumps(_DEFAULT_CONFIG, indent="\t", ensure_ascii=False), encoding="utf-8"
    )
    return dict(_DEFAULT_CONFIG)


def _cmd_infer(args: argparse.Namespace) -> None:
    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()

    if not input_dir.is_dir():
        sys.exit(f"Error: '{input_dir}' is not a directory.")

    py_files = sorted(input_dir.glob("**/*.py"))
    if not py_files:
        return
    output_dir.mkdir(parents=True, exist_ok=True)

    config = _load_config(output_dir)
    top_k: int = config.get("retrieval-top-k", _DEFAULT_CONFIG["retrieval-top-k"])

    _maybe_download_index(output_dir, config)

    pairs: list[tuple[Path, str]] = [
        (p, str(p.relative_to(input_dir))) for p in py_files
    ]
    pad = len(str(len(py_files) - 1))

    # Pass 1: collect skeleton entries and write initial JSONs immediately
    all_entries: dict[str, dict[str, dict]] = {}
    out_paths: dict[str, Path] = {}
    index: dict[str, str] = {}
    for i, (py_path, relpath) in enumerate(pairs):
        try:
            entries = collect_entries(py_path)
        except (SyntaxError, Exception):
            entries = {}
        all_entries[relpath] = entries
        out_name = f"{i:0{pad}}.json"
        out_path = output_dir / out_name
        out_paths[relpath] = out_path
        out_path.write_text(
            json.dumps(entries, indent="\t", ensure_ascii=False), encoding="utf-8"
        )
        index[relpath] = out_name

    (output_dir / "index.json").write_text(
        json.dumps(index, indent="\t", ensure_ascii=False), encoding="utf-8"
    )

    # Pass 2: build project-wide registry (classes, functions, field types)
    registry = Registry()
    collect([(p, r) for p, r in pairs], registry)

    # Pass 3: usage-driven inference
    for py_path, relpath in track(pairs, description="Usage inference    "):
        infer_file(py_path, relpath, registry, all_entries[relpath])
        out_paths[relpath].write_text(
            json.dumps(all_entries[relpath], indent="\t", ensure_ascii=False),
            encoding="utf-8",
        )

    # Pass 4: retrieval-driven inference (skipped if index is absent or disabled)
    index_dir = output_dir / "context-index"
    if config.get("context-retrieval", _DEFAULT_CONFIG["context-retrieval"]) and index_dir.is_dir():
        retriever = TypeRetriever(index_dir)
        for py_path, relpath in track(pairs, description="Retrieval inference"):
            retrieve_file(py_path, relpath, retriever, all_entries[relpath], top_k)
            out_paths[relpath].write_text(
                json.dumps(all_entries[relpath], indent="\t", ensure_ascii=False),
                encoding="utf-8",
            )

    # Pass 5: Type4Py inference (skipped if disabled in config)
    if config.get("type4py", _DEFAULT_CONFIG["type4py"]):
        api_url = config.get("type4py-api-url", _DEFAULT_CONFIG["type4py-api-url"])
        for py_path, relpath in track(pairs, description="Type4Py inference  "):
            type4py_infer_file(py_path, relpath, all_entries[relpath], api_url)
            out_paths[relpath].write_text(
                json.dumps(all_entries[relpath], indent="\t", ensure_ascii=False),
                encoding="utf-8",
            )


def _cmd_build(args: argparse.Namespace) -> None:
    build_index(
        dataset_root=args.dataset_root.resolve(),
        index_dir=args.index.resolve(),
        workers=args.workers,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    infer_parser = subparsers.add_parser("infer")
    infer_parser.add_argument("input_dir", type=Path)
    infer_parser.add_argument("output_dir", type=Path)

    build_parser = subparsers.add_parser("build", help="Build Tantivy index from a dataset")
    build_parser.add_argument("dataset_root", type=Path)
    build_parser.add_argument("index", type=Path)
    build_parser.add_argument("--workers", type=int, default=4)

    args = parser.parse_args()
    if args.command == "infer":
        _cmd_infer(args)
    elif args.command == "build":
        _cmd_build(args)


if __name__ == "__main__":
    main()
