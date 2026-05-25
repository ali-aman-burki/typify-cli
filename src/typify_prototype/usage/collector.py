from __future__ import annotations
import ast
from pathlib import Path
from .type_expr import TypeExpr, UNKNOWN, union, from_annotation
from .symbol_table import Registry, ClassInfo, FuncInfo


def collect(py_files: list[tuple[Path, str]], registry: Registry) -> None:
    for py_path, relpath in py_files:
        try:
            tree = ast.parse(py_path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        _CollectVisitor(relpath, registry).visit(tree)


class _CollectVisitor(ast.NodeVisitor):
    def __init__(self, relpath: str, registry: Registry) -> None:
        self._relpath = relpath
        self._registry = registry
        self._class_stack: list[str] = []

    def _cls_qname(self, cls_name: str) -> str:
        return f"{self._relpath}:{cls_name}"

    def _func_qname(self, func_name: str) -> str:
        if self._class_stack:
            return f"{self._relpath}:{self._class_stack[-1]}.{func_name}"
        return f"{self._relpath}:{func_name}"

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._registry.classes[self._cls_qname(node.name)] = ClassInfo(name=node.name)
        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        all_args = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
        if node.args.vararg:
            all_args.append(node.args.vararg)
        if node.args.kwarg:
            all_args.append(node.args.kwarg)
        params = [a.arg for a in all_args if a.arg != "self"]
        self._registry.functions[self._func_qname(node.name)] = FuncInfo(
            name=node.name, params=params
        )
        if node.name == "__init__" and self._class_stack:
            cls_info = self._registry.classes.get(self._cls_qname(self._class_stack[-1]))
            if cls_info is not None:
                _collect_init_fields(node, cls_info)

    visit_AsyncFunctionDef = visit_FunctionDef


def _collect_init_fields(node: ast.FunctionDef, cls_info: ClassInfo) -> None:
    for stmt in ast.walk(node):
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                ):
                    cls_info.fields[target.attr] = _literal_type_of(stmt.value)
        elif isinstance(stmt, ast.AnnAssign):
            if (
                isinstance(stmt.target, ast.Attribute)
                and isinstance(stmt.target.value, ast.Name)
                and stmt.target.value.id == "self"
            ):
                cls_info.fields[stmt.target.attr] = from_annotation(stmt.annotation) or UNKNOWN


def _literal_type_of(node: ast.expr) -> TypeExpr:
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, bool): return TypeExpr("bool")
        if isinstance(v, int): return TypeExpr("int")
        if isinstance(v, float): return TypeExpr("float")
        if isinstance(v, str): return TypeExpr("str")
        if isinstance(v, bytes): return TypeExpr("bytes")
        if v is None: return TypeExpr("None")
    if isinstance(node, ast.List):
        elem_t = _union_all(_literal_type_of(e) for e in node.elts)
        return TypeExpr("list", (elem_t,)) if elem_t != UNKNOWN else TypeExpr("list")
    if isinstance(node, ast.Dict):
        key_t = _union_all(_literal_type_of(k) for k in node.keys if k is not None)
        val_t = _union_all(_literal_type_of(v) for v in node.values)
        if key_t != UNKNOWN and val_t != UNKNOWN:
            return TypeExpr("dict", (key_t, val_t))
        return TypeExpr("dict")
    if isinstance(node, ast.Set):
        elem_t = _union_all(_literal_type_of(e) for e in node.elts)
        return TypeExpr("set", (elem_t,)) if elem_t != UNKNOWN else TypeExpr("set")
    if isinstance(node, ast.Tuple):
        elem_t = _union_all(_literal_type_of(e) for e in node.elts)
        return TypeExpr("tuple", (elem_t,)) if elem_t != UNKNOWN else TypeExpr("tuple")
    return UNKNOWN


def _union_all(types) -> TypeExpr:
    result = UNKNOWN
    for t in types:
        result = union(result, t)
    return result
