"""
Type4Py-driven type inference pass.

Posts each file to the Type4Py API, maps predictions to definition entries
using the coordinate information in the response, then propagates those
predictions through scope to all usage sites (same pattern as the retrieval
and usage-driven passes).

Coordinate formula (works for plain vars, self.attr, class vars, module vars):
    key = f"{lc[1][0]}:{lc[1][1] - len(name)}"
where lc = [[start_line, start_col], [end_line, end_col]] from *_var_ln fields.
"""

from __future__ import annotations

import ast
from pathlib import Path

from .client import predict, DEFAULT_API_URL

_SKIP_PARAMS = {"self", "cls", "args", "kwargs"}


def _preds_to_dict(predictions: list) -> dict[str, dict]:
    """Convert [[type_name, score], ...] → {type_name: {"score": score}}."""
    return {
        str(type_name): {"score": round(float(score), 6)}
        for type_name, score in predictions
    }


def _var_key(name: str, lc: list) -> str:
    """Entry key from a *_var_ln span: end_col - len(name) gives the name's start col."""
    end_line, end_col = lc[1]
    return f"{end_line}:{end_col - len(name)}"


def _write_dict(entries: dict, key: str, preds_dict: dict) -> None:
    if not preds_dict:
        return
    entry = entries.get(key)
    if entry and "type" in entry:
        entry["type"]["type4py"] = preds_dict


def _write(entries: dict, key: str, predictions: list) -> None:
    if predictions:
        _write_dict(entries, key, _preds_to_dict(predictions))


class _MapVisitor(ast.NodeVisitor):
    """
    Writes Type4Py predictions to definition entries and propagates them
    through scope to all usage (Name Load) sites.
    """

    def __init__(self, entries: dict, func_map: dict, response: dict) -> None:
        self._entries = entries
        # func_map: q_name (e.g. "Foo.__init__", "work") → function dict
        self._func_map = func_map
        self._response = response
        self._class_stack: list[str] = []

        # Scope stack: each frame maps name → already-computed type4py predictions dict.
        # Pre-populate the module frame with module-level variable predictions.
        module_scope: dict[str, dict] = {}
        mod_var_ln = response.get("mod_var_ln") or {}
        for var_name, preds in (response.get("variables_p") or {}).items():
            lc = mod_var_ln.get(var_name)
            if preds and lc:
                module_scope[var_name] = _preds_to_dict(preds)
        self._scope_stack: list[dict[str, dict]] = [module_scope]

    # ── scope helpers ─────────────────────────────────────────────────────────

    def _scope_get(self, name: str) -> dict:
        for frame in reversed(self._scope_stack):
            if name in frame:
                return frame[name]
        return {}

    def _scope_set(self, name: str, preds_dict: dict) -> None:
        self._scope_stack[-1][name] = preds_dict

    # ── visitors ──────────────────────────────────────────────────────────────

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._class_stack.append(node.name)

        # Build class scope from this class's variable predictions.
        cls_scope: dict[str, dict] = {}
        for cls_data in (self._response.get("classes") or []):
            if cls_data.get("name") == node.name:
                cls_var_ln = cls_data.get("cls_var_ln") or {}
                for var_name, preds in (cls_data.get("variables_p") or {}).items():
                    lc = cls_var_ln.get(var_name)
                    if preds and lc:
                        cls_scope[var_name] = _preds_to_dict(preds)
                break

        self._scope_stack.append(cls_scope)
        self.generic_visit(node)
        self._scope_stack.pop()
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        class_name = self._class_stack[-1] if self._class_stack else None
        q_name = f"{class_name}.{node.name}" if class_name else node.name
        func_data = self._func_map.get(q_name)

        func_scope: dict[str, dict] = {}

        if func_data:
            func_key = f"{node.lineno}:{node.col_offset + 4}"

            # Return type — written to the Function entry, not propagated via scope
            _write(self._entries, func_key, func_data.get("ret_type_p") or [])

            # Params: write to Parameter entry + Function's params dict + scope
            params_p = func_data.get("params_p") or {}
            func_entry = self._entries.get(func_key)
            all_args = (
                node.args.posonlyargs + node.args.args + node.args.kwonlyargs
            )
            for arg in all_args:
                if arg.arg in _SKIP_PARAMS:
                    continue
                preds = params_p.get(arg.arg)
                if not preds:
                    continue
                preds_dict = _preds_to_dict(preds)
                _write_dict(self._entries, f"{arg.lineno}:{arg.col_offset}", preds_dict)
                if func_entry and func_entry.get("node_type") == "Function":
                    param_slot = func_entry.get("params", {}).get(arg.arg)
                    if param_slot is not None:
                        param_slot["type4py"] = preds_dict
                func_scope[arg.arg] = preds_dict

            # Local variables: write to assignment entry + scope
            fn_var_ln = func_data.get("fn_var_ln") or {}
            for var_name, preds in (func_data.get("variables_p") or {}).items():
                lc = fn_var_ln.get(var_name)
                if lc:
                    preds_dict = _preds_to_dict(preds)
                    _write_dict(self._entries, _var_key(var_name, lc), preds_dict)
                    func_scope[var_name] = preds_dict

        self._scope_stack.append(func_scope)
        self.generic_visit(node)
        self._scope_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Name(self, node: ast.Name) -> None:
        if not isinstance(node.ctx, ast.Load):
            return
        preds_dict = self._scope_get(node.id)
        if preds_dict:
            _write_dict(self._entries, f"{node.lineno}:{node.col_offset}", preds_dict)


def infer_file(
    py_path: Path,
    relpath: str,
    entries: dict,
    api_url: str = DEFAULT_API_URL,
) -> None:
    """Call Type4Py API for one file and write predictions into entries in-place."""
    try:
        source = py_path.read_text(encoding="utf-8")
    except Exception:
        return

    response = predict(source, api_url)
    if response is None:
        return

    # Write definition-site entries for module-level and class-level variables directly,
    # since those are keyed by *_var_ln coordinates (not via AST walk).
    mod_var_ln = response.get("mod_var_ln") or {}
    for var_name, preds in (response.get("variables_p") or {}).items():
        lc = mod_var_ln.get(var_name)
        if lc:
            _write(entries, _var_key(var_name, lc), preds)

    for cls in response.get("classes") or []:
        cls_var_ln = cls.get("cls_var_ln") or {}
        for var_name, preds in (cls.get("variables_p") or {}).items():
            lc = cls_var_ln.get(var_name)
            if lc:
                _write(entries, _var_key(var_name, lc), preds)

    # Build q_name → func_data map for the AST visitor.
    func_map: dict[str, dict] = {}
    for func in response.get("funcs") or []:
        func_map[func["q_name"]] = func
    for cls in response.get("classes") or []:
        for func in cls.get("funcs") or []:
            func_map[func["q_name"]] = func

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return

    # Single AST pass: writes to definition entries, populates scope, propagates to usages.
    _MapVisitor(entries, func_map, response).visit(tree)
