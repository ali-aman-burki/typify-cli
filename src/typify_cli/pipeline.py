from __future__ import annotations
import ast
from pathlib import Path


class ScopeVisitor(ast.NodeVisitor):
    def __init__(self):
        self.entries: dict[str, dict] = {}
        self._scope_stack: list[str] = []
        self._annotatable_lhs: set[tuple[int, int]] = set()

    @property
    def _scope(self) -> str:
        return ".".join(self._scope_stack)

    def _record(self, line: int, col: int, identifier: str, node_type: str, params: list[str] | None = None) -> None:
        entry = {"scope": self._scope, "identifier": identifier, "node_type": node_type}
        if node_type in ("Function", "Parameter"):
            entry["annotatable"] = True
        elif node_type == "Name":
            entry["annotatable"] = (line, col) in self._annotatable_lhs
        else:
            entry["annotatable"] = False
        if node_type != "Class":
            entry["type"] = {"usage": "", "retrieved": {}, "type4py": {}}
        if node_type not in ("Function", "Class", "Parameter"):
            entry["goto"] = ""
        if node_type == "Function":
            entry["params"] = {p: {"usage": "", "retrieved": {}, "type4py": {}} for p in (params or [])}
            entry["callsites"] = {}
        self.entries[f"{line}:{col}"] = entry

    def visit_Name(self, node: ast.Name) -> None:
        self._record(node.lineno, node.col_offset, node.id, "Name")
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name):
                self._annotatable_lhs.add((target.lineno, target.col_offset))
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name):
            self._annotatable_lhs.add((node.target.lineno, node.target.col_offset))
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
                col += len(part) + 1

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


def collect_entries(py_path: Path) -> dict:
    tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
    visitor = ScopeVisitor()
    visitor.visit(tree)
    return dict(sorted(visitor.entries.items(), key=lambda kv: tuple(int(x) for x in kv[0].split(":"))))
