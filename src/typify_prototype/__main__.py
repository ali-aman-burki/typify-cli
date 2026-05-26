import json
import argparse
import sys
from pathlib import Path

from .pipeline import collect_entries
from .usage.symbol_table import Registry
from .usage.collector import collect
from .usage.infer import infer_file
from .retrieval.build import build_index

_DEFAULT_CONFIG = {
    "context-retrieval": True,
    "augment-context": False,
    "deep-learn": False,
}


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

    _load_config(output_dir)

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

    # Pass 3: infer types per file; update JSON immediately after each file
    for py_path, relpath in pairs:
        infer_file(py_path, relpath, registry, all_entries[relpath])
        out_paths[relpath].write_text(
            json.dumps(all_entries[relpath], indent="\t", ensure_ascii=False), encoding="utf-8"
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
