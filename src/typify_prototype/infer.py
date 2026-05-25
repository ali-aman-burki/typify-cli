from __future__ import annotations
import ast
from pathlib import Path
from .type_expr import TypeExpr, UNKNOWN, union, from_annotation
from .symbol_table import Registry, Scope


_BUILTINS: dict[str, TypeExpr] = {
    "len": TypeExpr("int"),
    "range": TypeExpr("range"),
    "enumerate": TypeExpr("enumerate"),
    "zip": TypeExpr("zip"),
    "map": TypeExpr("map"),
    "filter": TypeExpr("filter"),
    "int": TypeExpr("int"),
    "str": TypeExpr("str"),
    "float": TypeExpr("float"),
    "bool": TypeExpr("bool"),
    "list": TypeExpr("list"),
    "dict": TypeExpr("dict"),
    "set": TypeExpr("set"),
    "tuple": TypeExpr("tuple"),
    "bytes": TypeExpr("bytes"),
    "print": TypeExpr("None"),
    "sorted": TypeExpr("list"),
    "reversed": TypeExpr("reversed"),
    "abs": TypeExpr("int"),
    "sum": TypeExpr("int"),
    "input": TypeExpr("str"),
    "type": TypeExpr("type"),
    "isinstance": TypeExpr("bool"),
    "issubclass": TypeExpr("bool"),
    "hasattr": TypeExpr("bool"),
    "callable": TypeExpr("bool"),
    "any": TypeExpr("bool"),
    "all": TypeExpr("bool"),
    "id": TypeExpr("int"),
    "hash": TypeExpr("int"),
    "repr": TypeExpr("str"),
    "format": TypeExpr("str"),
    "open": TypeExpr("IO"),
    "vars": TypeExpr("dict"),
    "dir": TypeExpr("list"),
    "chr": TypeExpr("str"),
    "ord": TypeExpr("int"),
    "hex": TypeExpr("str"),
    "oct": TypeExpr("str"),
    "bin": TypeExpr("str"),
    "round": TypeExpr("int"),
}

_METHOD_TABLE: dict[str, dict[str, TypeExpr]] = {
    "str": {
        "upper": TypeExpr("str"), "lower": TypeExpr("str"), "strip": TypeExpr("str"),
        "lstrip": TypeExpr("str"), "rstrip": TypeExpr("str"),
        "split": TypeExpr("list", (TypeExpr("str"),)),
        "rsplit": TypeExpr("list", (TypeExpr("str"),)),
        "splitlines": TypeExpr("list", (TypeExpr("str"),)),
        "join": TypeExpr("str"), "replace": TypeExpr("str"), "format": TypeExpr("str"),
        "encode": TypeExpr("bytes"), "startswith": TypeExpr("bool"),
        "endswith": TypeExpr("bool"), "find": TypeExpr("int"),
        "rfind": TypeExpr("int"), "index": TypeExpr("int"), "count": TypeExpr("int"),
        "isdigit": TypeExpr("bool"), "isalpha": TypeExpr("bool"),
        "isalnum": TypeExpr("bool"), "islower": TypeExpr("bool"),
        "isupper": TypeExpr("bool"), "isspace": TypeExpr("bool"),
        "title": TypeExpr("str"), "capitalize": TypeExpr("str"),
        "zfill": TypeExpr("str"), "ljust": TypeExpr("str"), "rjust": TypeExpr("str"),
        "center": TypeExpr("str"), "expandtabs": TypeExpr("str"),
        "partition": TypeExpr("tuple"), "rpartition": TypeExpr("tuple"),
        "removeprefix": TypeExpr("str"), "removesuffix": TypeExpr("str"),
        "format_map": TypeExpr("str"),
    },
    "bytes": {
        "decode": TypeExpr("str"), "upper": TypeExpr("bytes"),
        "lower": TypeExpr("bytes"), "split": TypeExpr("list", (TypeExpr("bytes"),)),
        "strip": TypeExpr("bytes"), "startswith": TypeExpr("bool"),
        "endswith": TypeExpr("bool"), "count": TypeExpr("int"), "find": TypeExpr("int"),
        "hex": TypeExpr("str"),
    },
    "list": {
        "append": TypeExpr("None"), "extend": TypeExpr("None"),
        "insert": TypeExpr("None"), "remove": TypeExpr("None"),
        "sort": TypeExpr("None"), "reverse": TypeExpr("None"),
        "clear": TypeExpr("None"), "copy": TypeExpr("list"),
        "count": TypeExpr("int"), "index": TypeExpr("int"),
    },
    "dict": {
        "update": TypeExpr("None"), "clear": TypeExpr("None"),
        "copy": TypeExpr("dict"),
        "keys": TypeExpr("KeysView"), "values": TypeExpr("ValuesView"),
        "items": TypeExpr("ItemsView"),
    },
    "set": {
        "add": TypeExpr("None"), "remove": TypeExpr("None"),
        "discard": TypeExpr("None"), "clear": TypeExpr("None"),
        "copy": TypeExpr("set"), "union": TypeExpr("set"),
        "intersection": TypeExpr("set"), "difference": TypeExpr("set"),
        "issubset": TypeExpr("bool"), "issuperset": TypeExpr("bool"),
        "isdisjoint": TypeExpr("bool"),
    },
}


def infer_file(py_path: Path, relpath: str, registry: Registry, entries: dict[str, dict]) -> None:
    try:
        tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
    except SyntaxError:
        return
    _InferVisitor(relpath, registry, entries).visit(tree)


class _InferVisitor(ast.NodeVisitor):
    def __init__(self, relpath: str, registry: Registry, entries: dict[str, dict]) -> None:
        self._relpath = relpath
        self._registry = registry
        self._entries = entries
        self._scope = Scope()
        self._class_stack: list[str] = []

    # ── helpers ──────────────────────────────────────────────────────────────

    def _key(self, line: int, col: int) -> str:
        return f"{line}:{col}"

    def _set_type(self, key: str, t: TypeExpr) -> None:
        if t != UNKNOWN and key in self._entries:
            self._entries[key]["type"] = str(t)

    def _current_class(self) -> str | None:
        return self._class_stack[-1] if self._class_stack else None

    def _is_class_name(self, name: str) -> bool:
        for key in self._registry.classes:
            if key.endswith(f":{name}"):
                return True
        return False

    def _class_info_for(self, type_name: str):
        for key, info in self._registry.classes.items():
            if key.endswith(f":{type_name}"):
                return info
        return None

    def _func_info_for(self, func_name: str):
        cls = self._current_class()
        if cls:
            fi = self._registry.functions.get(f"{self._relpath}:{cls}.{func_name}")
            if fi:
                return fi
        return self._registry.functions.get(f"{self._relpath}:{func_name}")

    # ── scope-managing visitors ───────────────────────────────────────────

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._class_stack.append(node.name)
        outer = self._scope
        self._scope = Scope(parent=outer)
        for stmt in node.body:
            self.visit(stmt)
        self._scope = outer
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        all_args = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
        if node.args.vararg:
            all_args.append(node.args.vararg)
        if node.args.kwarg:
            all_args.append(node.args.kwarg)

        outer = self._scope
        self._scope = Scope(parent=outer)

        for arg in all_args:
            if arg.arg == "self":
                cls = self._current_class()
                if cls:
                    self._scope.set("self", TypeExpr(cls))
                continue
            t = from_annotation(arg.annotation) or UNKNOWN
            self._scope.set(arg.arg, t)
            self._set_type(self._key(arg.lineno, arg.col_offset), t)

        for deco in node.decorator_list:
            self.visit(deco)
        for stmt in node.body:
            self.visit(stmt)

        # Infer return type after body so local vars are in scope
        if node.returns:
            ret_t = from_annotation(node.returns) or UNKNOWN
        else:
            ret_exprs = list(_iter_return_exprs(node.body))
            ret_t = _union_all(self._infer_expr(e) for e in ret_exprs) if ret_exprs else UNKNOWN

        func_key = self._key(node.lineno, node.col_offset + 4)
        self._set_type(func_key, ret_t)

        # Push return type into the registry so callers can use it
        cls = self._current_class()
        qname = (
            f"{self._relpath}:{cls}.{node.name}" if cls
            else f"{self._relpath}:{node.name}"
        )
        fi = self._registry.functions.get(qname)
        if fi and ret_t != UNKNOWN:
            fi.return_type = ret_t

        # Update Function entry's params with inferred types
        entry = self._entries.get(func_key)
        if entry and entry.get("node_type") == "Function":
            for arg in all_args:
                if arg.arg == "self":
                    continue
                t = self._scope.get(arg.arg)
                if t != UNKNOWN:
                    entry["params"][arg.arg] = str(t)

        self._scope = outer

    visit_AsyncFunctionDef = visit_FunctionDef

    # ── assignment visitors ───────────────────────────────────────────────

    def visit_Assign(self, node: ast.Assign) -> None:
        t = self._infer_expr(node.value)
        for target in node.targets:
            self._assign_target(target, t)
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        t = from_annotation(node.annotation) or UNKNOWN
        if node.value is not None:
            inferred = self._infer_expr(node.value)
            if t == UNKNOWN:
                t = inferred
            self.visit(node.value)
        self._assign_target(node.target, t)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.visit(node.value)

    def _assign_target(self, target: ast.expr, t: TypeExpr) -> None:
        if isinstance(target, ast.Name):
            self._scope.set(target.id, t)
            self._set_type(self._key(target.lineno, target.col_offset), t)
        elif isinstance(target, ast.Attribute):
            if (
                isinstance(target.value, ast.Name)
                and target.value.id == "self"
                and self._current_class()
            ):
                cls_key = f"{self._relpath}:{self._current_class()}"
                cls_info = self._registry.classes.get(cls_key)
                if cls_info is not None and t != UNKNOWN:
                    cls_info.fields[target.attr] = t
        elif isinstance(target, (ast.Tuple, ast.List)):
            # Unpacking: skip individual type assignment for now
            for elt in target.elts:
                self._assign_target(elt, UNKNOWN)

    # ── expression-visiting (mirrors ScopeVisitor traversal) ─────────────

    def visit_Name(self, node: ast.Name) -> None:
        self._set_type(self._key(node.lineno, node.col_offset), self._scope.get(node.id))

    def visit_Call(self, node: ast.Call) -> None:
        t = self._infer_call(node)
        if isinstance(node.func, ast.Attribute):
            key = self._key(
                node.func.end_lineno,
                node.func.end_col_offset - len(node.func.attr),
            )
            self._set_type(key, t)
            self.visit(node.func.value)
        elif isinstance(node.func, ast.Name):
            self._set_type(self._key(node.func.lineno, node.func.col_offset), t)
        else:
            self.visit(node.func)
        for arg in node.args:
            self.visit(arg)
        for kw in node.keywords:
            self.visit(kw.value)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        key = self._key(node.end_lineno, node.end_col_offset - len(node.attr))
        self._set_type(key, self._infer_attribute(node))
        if isinstance(node.value, ast.Call):
            self.visit_Call(node.value)
        else:
            self.visit(node.value)

    # ── type inference ────────────────────────────────────────────────────

    def _infer_expr(self, node: ast.expr) -> TypeExpr:
        if isinstance(node, ast.Constant):
            return _literal_type(node)
        if isinstance(node, ast.Name):
            return self._scope.get(node.id)
        if isinstance(node, ast.List):
            elem_t = _union_all(self._infer_expr(e) for e in node.elts)
            return TypeExpr("list", (elem_t,)) if elem_t != UNKNOWN else TypeExpr("list")
        if isinstance(node, ast.Dict):
            key_t = _union_all(self._infer_expr(k) for k in node.keys if k is not None)
            val_t = _union_all(self._infer_expr(v) for v in node.values)
            if key_t != UNKNOWN and val_t != UNKNOWN:
                return TypeExpr("dict", (key_t, val_t))
            return TypeExpr("dict")
        if isinstance(node, ast.Set):
            elem_t = _union_all(self._infer_expr(e) for e in node.elts)
            return TypeExpr("set", (elem_t,)) if elem_t != UNKNOWN else TypeExpr("set")
        if isinstance(node, ast.Tuple):
            elem_t = _union_all(self._infer_expr(e) for e in node.elts)
            return TypeExpr("tuple", (elem_t,)) if elem_t != UNKNOWN else TypeExpr("tuple")
        if isinstance(node, ast.Call):
            return self._infer_call(node)
        if isinstance(node, ast.Attribute):
            return self._infer_attribute(node)
        if isinstance(node, ast.BinOp):
            return self._infer_binop(node)
        if isinstance(node, ast.JoinedStr):
            return TypeExpr("str")
        if isinstance(node, ast.BoolOp):
            return _union_all(self._infer_expr(v) for v in node.values)
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                return TypeExpr("bool")
            return self._infer_expr(node.operand)
        if isinstance(node, ast.Compare):
            return TypeExpr("bool")
        if isinstance(node, ast.IfExp):
            return union(self._infer_expr(node.body), self._infer_expr(node.orelse))
        if isinstance(node, ast.Lambda):
            return TypeExpr("Callable")
        if isinstance(node, ast.ListComp):
            return TypeExpr("list")
        if isinstance(node, ast.DictComp):
            return TypeExpr("dict")
        if isinstance(node, ast.SetComp):
            return TypeExpr("set")
        if isinstance(node, ast.GeneratorExp):
            return TypeExpr("Generator")
        return UNKNOWN

    def _infer_call(self, node: ast.Call) -> TypeExpr:
        if isinstance(node.func, ast.Name):
            name = node.func.id
            if self._is_class_name(name):
                return TypeExpr(name)
            if name in _BUILTINS:
                return _BUILTINS[name]
            fi = self._func_info_for(name)
            if fi and fi.return_type != UNKNOWN:
                return fi.return_type
        elif isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            val_t = self._infer_expr(node.func.value)
            methods = _METHOD_TABLE.get(val_t.base, {})
            if attr in methods:
                return methods[attr]
            # Parametric element/value returns
            if val_t.base == "list" and attr == "pop" and val_t.args:
                return val_t.args[0]
            if val_t.base == "dict" and attr in ("get", "pop", "setdefault") and len(val_t.args) >= 2:
                return val_t.args[1]
        return UNKNOWN

    def _infer_attribute(self, node: ast.Attribute) -> TypeExpr:
        val_t = self._infer_expr(node.value)
        if val_t == UNKNOWN:
            return UNKNOWN
        cls_info = self._class_info_for(val_t.base)
        if cls_info and node.attr in cls_info.fields:
            return cls_info.fields[node.attr]
        return UNKNOWN

    def _infer_binop(self, node: ast.BinOp) -> TypeExpr:
        lt = self._infer_expr(node.left)
        rt = self._infer_expr(node.right)
        _numeric = {TypeExpr("int"), TypeExpr("float"), TypeExpr("complex")}
        # "fmt" % args → str
        if isinstance(node.op, ast.Mod) and lt == TypeExpr("str"):
            return TypeExpr("str")
        if lt == rt and lt in _numeric | {TypeExpr("str"), TypeExpr("bytes"), TypeExpr("list")}:
            return lt
        if lt in _numeric and rt in _numeric:
            if TypeExpr("complex") in (lt, rt): return TypeExpr("complex")
            if TypeExpr("float") in (lt, rt): return TypeExpr("float")
            return TypeExpr("int")
        return UNKNOWN


def _literal_type(node: ast.Constant) -> TypeExpr:
    v = node.value
    if isinstance(v, bool): return TypeExpr("bool")
    if isinstance(v, int): return TypeExpr("int")
    if isinstance(v, float): return TypeExpr("float")
    if isinstance(v, str): return TypeExpr("str")
    if isinstance(v, bytes): return TypeExpr("bytes")
    if v is None: return TypeExpr("None")
    return UNKNOWN


def _union_all(types) -> TypeExpr:
    result = UNKNOWN
    for t in types:
        result = union(result, t)
    return result


def _iter_return_exprs(body: list[ast.stmt]):
    """Yield return-value expressions without crossing nested scope boundaries."""
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(stmt, ast.Return) and stmt.value is not None:
            yield stmt.value
            continue
        for _field, val in ast.iter_fields(stmt):
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, ast.stmt):
                        yield from _iter_return_exprs([item])
