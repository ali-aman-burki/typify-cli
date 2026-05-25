import json
import argparse
import sys
from pathlib import Path

from .pipeline import collect_entries
from .usage.symbol_table import Registry
from .usage.collector import collect
from .usage.infer import infer_file


def _cmd_infer(args: argparse.Namespace) -> None:
    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()

    if not input_dir.is_dir():
        sys.exit(f"Error: '{input_dir}' is not a directory.")

    py_files = sorted(input_dir.glob("**/*.py"))
    if not py_files:
        return
    output_dir.mkdir(parents=True, exist_ok=True)

    pairs: list[tuple[Path, str]] = [
        (p, str(p.relative_to(input_dir))) for p in py_files
    ]

    # Pass 1: collect entries (schema skeleton)
    all_entries: dict[str, dict[str, dict]] = {}
    for py_path, relpath in pairs:
        try:
            all_entries[relpath] = collect_entries(py_path)
        except (SyntaxError, Exception):
            all_entries[relpath] = {}

    # Pass 2: build project-wide registry (classes, functions, field types)
    registry = Registry()
    collect([(p, r) for p, r in pairs], registry)

    # Pass 3: infer types into each file's entries
    for py_path, relpath in pairs:
        infer_file(py_path, relpath, registry, all_entries[relpath])

    # Write output
    pad = len(str(len(py_files) - 1))
    index: dict[str, str] = {}
    for i, (_, relpath) in enumerate(pairs):
        out_name = f"{i:0{pad}}.json"
        out_path = output_dir / out_name
        entries = all_entries[relpath]
        out_path.write_text(
            json.dumps(entries, indent="\t", ensure_ascii=False), encoding="utf-8"
        )
        index[relpath] = out_name

    (output_dir / "index.json").write_text(
        json.dumps(index, indent="\t", ensure_ascii=False), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    infer_parser = subparsers.add_parser("infer")
    infer_parser.add_argument("input_dir", type=Path)
    infer_parser.add_argument("output_dir", type=Path)

    args = parser.parse_args()
    if args.command == "infer":
        _cmd_infer(args)


if __name__ == "__main__":
    main()
