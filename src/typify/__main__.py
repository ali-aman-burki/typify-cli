from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from typify.analyzer import ProjectAnalyzer


def _file_json(fr) -> dict:
    if fr.parse_error:
        return {"filepath": fr.filepath, "module": fr.module_name, "parse_error": fr.parse_error}
    seen = set()
    bindings = []
    for qname, sym in fr.result.bindings:
        if qname in seen:
            continue
        seen.add(qname)
        bindings.append({
            "name": qname,
            "type": str(sym.inferred_type),
            "line": sym.defined_at[1] if sym.defined_at else None,
            "col": sym.defined_at[2] if sym.defined_at else None,
        })
    return {
        "filepath": fr.filepath,
        "module": fr.module_name,
        "bindings": bindings,
        "function_returns": {k: str(v) for k, v in fr.result.function_returns.items()},
        "class_attrs": {k: str(v) for k, v in fr.result.class_attrs.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="typify",
        description="Static type inference for unannotated Python projects",
    )
    parser.add_argument("project_dir", help="Project directory to analyse")
    parser.add_argument("outdir", help="Output directory for per-file JSON results")

    args = parser.parse_args()

    target = Path(args.project_dir)
    if not target.exists() or not target.is_dir():
        print(f"Error: {target} is not a directory", file=sys.stderr)
        return 1

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    analyzer = ProjectAnalyzer(str(target))
    proj = analyzer.analyze()

    width = len(str(len(proj.files) - 1)) if proj.files else 1
    index = {}

    for i, fr in enumerate(proj.files):
        filename = f"{str(i).zfill(width)}.json"
        rel_py = Path(fr.filepath).relative_to(target.resolve())
        index[str(rel_py)] = filename
        (outdir / filename).write_text(json.dumps(_file_json(fr), indent=2))

    (outdir / "index.json").write_text(json.dumps(index, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
