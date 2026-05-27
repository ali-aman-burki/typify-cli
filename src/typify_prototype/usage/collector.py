from __future__ import annotations
import ast
from pathlib import Path
from .type_expr import TypeExpr, UNKNOWN, union, from_annotation
from .symbol_table import Registry, ClassInfo, FuncInfo, ImportInfo


def collect(py_files: list[tuple[Path, str]], registry: Registry) -> None:
    # Build module index first so import resolution works during collection.
    for _, relpath in py_files:
        p = Path(relpath)
        if p.name == "__init__.py":
            parts = p.parts[:-1]
        else:
            parts = p.with_suffix("").parts
        if parts:
            registry.module_index[".".join(parts)] = relpath

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
        params = [a.arg for a in all_args]
        param_keys = {a.arg: f"{a.lineno}:{a.col_offset}" for a in all_args}
        fi = FuncInfo(
            name=node.name,
            class_name=self._class_stack[-1] if self._class_stack else "",
            params=params,
            param_keys=param_keys,
            def_relpath=self._relpath,
            def_key=f"{node.lineno}:{node.col_offset + 4}",
        )
        self._registry.functions[self._func_qname(node.name)] = fi

        # Pre-compute return type so cross-file callers can use it in Pass 2.
        if node.returns:
            t = from_annotation(node.returns)
            if t:
                fi.return_type = t
        else:
            has_value_returns = False
            for expr in _iter_return_exprs(node):
                has_value_returns = True
                t = _literal_type_of(expr)
                if t != UNKNOWN:
                    fi.return_type = union(fi.return_type, t)
            if not has_value_returns or _has_bare_return(node.body):
                fi.return_type = union(fi.return_type, TypeExpr("None"))

        if node.name == "__init__" and self._class_stack:
            cls_info = self._registry.classes.get(self._cls_qname(self._class_stack[-1]))
            if cls_info is not None:
                _collect_init_fields(node, cls_info)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node: ast.Assign) -> None:
        if self._class_stack:
            return  # only capture module-level assignments
        t = _literal_type_of(node.value)
        if t == UNKNOWN:
            return
        vars_ = self._registry.module_vars.setdefault(self._relpath, {})
        for target in node.targets:
            if isinstance(target, ast.Name):
                vars_[target.id] = t

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if self._class_stack:
            return
        t = from_annotation(node.annotation) or UNKNOWN
        if t == UNKNOWN and node.value is not None:
            t = _literal_type_of(node.value)
        if t != UNKNOWN and isinstance(node.target, ast.Name):
            self._registry.module_vars.setdefault(self._relpath, {})[node.target.id] = t

    def visit_Import(self, node: ast.Import) -> None:
        info = self._registry.imports.setdefault(self._relpath, ImportInfo())
        for alias in node.names:
            # Resolve the top-level module name to a relpath.
            source_rp = (
                self._registry.module_index.get(alias.name)
                or self._registry.module_index.get(alias.name.split(".")[0])
            )
            if source_rp:
                local = alias.asname or alias.name.split(".")[0]
                info.modules[local] = source_rp

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        info = self._registry.imports.setdefault(self._relpath, ImportInfo())
        abs_mod = self._abs_module(node.module or "", node.level)
        source_rp = self._registry.module_index.get(abs_mod) if abs_mod else None
        if source_rp is None:
            return
        for alias in node.names:
            if alias.name == "*":
                continue
            local = alias.asname or alias.name
            info.names[local] = (source_rp, alias.name)

    def _abs_module(self, module: str, level: int) -> str | None:
        """Resolve a relative import level+module to an absolute dotted module name."""
        if level == 0:
            return module or None
        pkg_parts = list(Path(self._relpath).parts[:-1])
        for _ in range(level - 1):
            if pkg_parts:
                pkg_parts.pop()
        pkg = ".".join(pkg_parts)
        if module:
            return f"{pkg}.{module}" if pkg else module
        return pkg or None


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


def _iter_return_exprs(func_node: ast.FunctionDef):
    """Yield return-value expression nodes without crossing nested scope boundaries."""
    def _walk(stmts):
        for stmt in stmts:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(stmt, ast.Return) and stmt.value is not None:
                yield stmt.value
            for _, val in ast.iter_fields(stmt):
                if isinstance(val, list):
                    for item in val:
                        if isinstance(item, ast.stmt):
                            yield from _walk([item])
    yield from _walk(func_node.body)


def _has_bare_return(body: list[ast.stmt]) -> bool:
    """Return True if any bare `return` (no expression) exists, without crossing nested scopes."""
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(stmt, ast.Return) and stmt.value is None:
            return True
        for _, val in ast.iter_fields(stmt):
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, ast.stmt) and _has_bare_return([item]):
                        return True
    return False
