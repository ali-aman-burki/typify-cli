import ast
import json
import argparse
import sys
from pathlib import Path

from .symbol_table import Registry
from .collector import collect
from .infer import infer_file


class ScopeVisitor(ast.NodeVisitor):
    def __init__(self):
        self.entries: dict[str, dict] = {}
        self._scope_stack: list[str] = []

    @property
    def _scope(self) -> str:
        return ".".join(self._scope_stack)

    def _record(self, line: int, col: int, identifier: str, node_type: str, params: list[str] | None = None) -> None:
        entry = {"scope": self._scope, "identifier": identifier, "node_type": node_type}
        if node_type != "Class":
            entry["type"] = ""
        if node_type not in ("Function", "Class", "Parameter"):
            entry["goto"] = ""
        if node_type == "Function":
            entry["params"] = {p: "" for p in (params or [])}
            entry["callsites"] = {}
        self.entries[f"{line}:{col}"] = entry

    def visit_Name(self, node: ast.Name) -> None:
        self._record(node.lineno, node.col_offset, node.id, "Name")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute):
            self._record(
                node.func.end_lineno,
                node.func.end_col_offset - len(node.func.attr),
                node.func.attr,
                "Call",
            )
            self.visit(node.func.value)
        elif isinstance(node.func, ast.Name):
            self._record(node.func.lineno, node.func.col_offset, node.func.id, "Call")
        else:
            self.visit(node.func)

        for arg in node.args:
            self.visit(arg)
        for kw in node.keywords:
            self.visit(kw.value)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._record(node.end_lineno, node.end_col_offset - len(node.attr), node.attr, "Name")
        if isinstance(node.value, ast.Call):
            self.visit_Call(node.value)
        else:
            self.visit(node.value)

    def visit_arg(self, node: ast.arg) -> None:
        self._record(node.lineno, node.col_offset, node.arg, "Parameter")
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.asname if alias.asname else alias.name.split(".")[0]
            self._record(alias.lineno, alias.col_offset, name, "Name")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            parts = node.module.split(".")
            col = 5
            for part in parts:
                self._record(node.lineno, col, part, "Name")
                col += len(part) + 1  # +1 for the "."

        for alias in node.names:
            name = alias.asname if alias.asname else alias.name
            self._record(alias.lineno, alias.col_offset, name, "Name")
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        all_args = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
        if node.args.vararg:
            all_args.append(node.args.vararg)
        if node.args.kwarg:
            all_args.append(node.args.kwarg)
        params = [a.arg for a in all_args]
        self._record(node.lineno, node.col_offset + 4, node.name, "Function", params=params)
        self._scope_stack.append(f"F:{node.name}")
        self.generic_visit(node)
        self._scope_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._record(node.lineno, node.col_offset + 6, node.name, "Class")
        self._scope_stack.append(f"C:{node.name}")
        self.generic_visit(node)
        self._scope_stack.pop()


def _collect_entries(py_path: Path) -> dict:
    tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
    visitor = ScopeVisitor()
    visitor.visit(tree)
    return dict(sorted(visitor.entries.items(), key=lambda kv: tuple(int(x) for x in kv[0].split(":"))))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()

    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()

    if not input_dir.is_dir():
        sys.exit(f"Error: '{input_dir}' is not a directory.")

    py_files = sorted(input_dir.glob("**/*.py"))
    if not py_files:
        return
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build (path, relpath) pairs
    pairs: list[tuple[Path, str]] = [
        (p, str(p.relative_to(input_dir))) for p in py_files
    ]

    # Pass 1: collect entries (schema skeleton)
    all_entries: dict[str, dict[str, dict]] = {}
    for py_path, relpath in pairs:
        try:
            all_entries[relpath] = _collect_entries(py_path)
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
        if not entries:
            continue
        out_path.write_text(
            json.dumps(entries, indent="\t", ensure_ascii=False), encoding="utf-8"
        )
        index[relpath] = out_name

    (output_dir / "index.json").write_text(
        json.dumps(index, indent="\t", ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
