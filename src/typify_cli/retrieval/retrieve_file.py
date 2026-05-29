"""
Retrieval-driven type inference pass.

Walks each file's AST, builds QueryContext objects for eligible sites
(params, variables, returns), queries the Tantivy index, and writes
results into the `retrieved` field of each entry in `entries`.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Optional

from .query import TypeRetriever, QueryContext, TypeCandidate
from .features import (
    _default_value_kind,
    _function_name_flags,
    _decorator_names,
    _extract_usage,
)


def _candidates_to_dict(candidates: list[TypeCandidate], top_k: int) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for tc in candidates[:top_k]:
        result[tc.annotated_type] = {"score": round(tc.score, 4), "hits": tc.hit_count}
    return result


def _round_robin_merge(
    candidate_lists: list[list[TypeCandidate]], top_k: int
) -> dict[str, dict]:
    if not candidate_lists:
        return {}
    result: dict[str, dict] = {}
    max_len = max(len(lst) for lst in candidate_lists)
    for i in range(max_len):
        for lst in candidate_lists:
            if i < len(lst):
                tc = lst[i]
                if tc.annotated_type not in result:
                    result[tc.annotated_type] = {
                        "score": round(tc.score, 4),
                        "hits": tc.hit_count,
                    }
                if len(result) >= top_k:
                    return result
    return result


class _RetrievalVisitor(ast.NodeVisitor):
    def __init__(
        self,
        relpath: str,
        retriever: TypeRetriever,
        entries: dict[str, dict],
        top_k: int,
    ) -> None:
        self._relpath = relpath
        self._retriever = retriever
        self._entries = entries
        self._top_k = top_k
        # Scope: name → list of per-assignment TypeCandidate lists (one list per assignment site)
        self._scope_stack: list[dict[str, list[list[TypeCandidate]]]] = [{}]
        # Return candidates: qualified_name → TypeCandidate list
        self._return_candidates: dict[str, list[TypeCandidate]] = {}
        self._class_stack: list[str] = []

    # ── scope helpers ─────────────────────────────────────────────────────────

    def _scope_lookup(self, name: str) -> list[list[TypeCandidate]]:
        for frame in reversed(self._scope_stack):
            if name in frame:
                return frame[name]
        return []

    def _scope_assign(self, name: str, candidates: list[TypeCandidate]) -> None:
        frame = self._scope_stack[-1]
        frame[name] = frame.get(name, []) + [candidates]

    def _merged_candidates(self, name: str) -> dict[str, dict]:
        return _round_robin_merge(self._scope_lookup(name), self._top_k)

    # ── entry writing ─────────────────────────────────────────────────────────

    def _key(self, line: int, col: int) -> str:
        return f"{line}:{col}"

    def _write_retrieved(self, key: str, d: dict[str, dict]) -> None:
        if not d:
            return
        entry = self._entries.get(key)
        if entry and "type" in entry:
            entry["type"]["retrieved"] = d

    def _write_param_in_func_entry(
        self,
        func_node: ast.FunctionDef,
        param_name: str,
        candidates: list[TypeCandidate],
    ) -> None:
        func_key = self._key(func_node.lineno, func_node.col_offset + 4)
        func_entry = self._entries.get(func_key)
        if func_entry and func_entry.get("node_type") == "Function":
            params_dict = func_entry.get("params", {})
            if param_name in params_dict:
                params_dict[param_name]["retrieved"] = _candidates_to_dict(
                    candidates, self._top_k
                )

    # ── visitors ──────────────────────────────────────────────────────────────

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._class_stack.append(node.name)
        self._scope_stack.append({})
        self.generic_visit(node)
        self._scope_stack.pop()
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        class_name = self._class_stack[-1] if self._class_stack else None
        func_name = node.name
        decorators = _decorator_names(node.decorator_list)
        name_flags = _function_name_flags(func_name)

        all_positional = node.args.posonlyargs + node.args.args
        kwonly = node.args.kwonlyargs
        n_pos = len(all_positional)
        n_defaults = len(node.args.defaults)
        defaults_map: dict[int, ast.expr] = {
            n_pos - n_defaults + i: d for i, d in enumerate(node.args.defaults)
        }
        kwonly_defaults: dict[int, ast.expr] = {
            i: d for i, d in enumerate(node.args.kw_defaults) if d is not None
        }
        sibling_info: list[tuple[str, Optional[str]]] = [
            (p.arg, None) for p in all_positional + kwonly
        ]

        self._scope_stack.append({})

        # ── positional / pos-only params ──────────────────────────────────────
        for pos, param in enumerate(all_positional):
            if param.arg == "self":
                continue
            usage = _extract_usage(param.arg, node.body)
            siblings = [(n, t) for i, (n, t) in enumerate(sibling_info) if i != pos]
            ctx = QueryContext(
                kind="param",
                identifier=param.arg,
                function_name=func_name,
                class_name=class_name,
                decorators=decorators,
                default_value_kind=_default_value_kind(defaults_map.get(pos)),
                sibling_params=siblings,
                param_position=pos,
                function_name_flags=name_flags,
                is_iterated=usage["is_iterated"],
                is_indexed=usage["is_indexed"],
                is_called=usage["is_called"],
                is_none_compared=usage["is_none_compared"],
                attribute_accesses=usage["attribute_accesses"],
            )
            candidates = self._retriever.query(ctx, top_k=self._top_k)
            self._write_retrieved(
                self._key(param.lineno, param.col_offset),
                _candidates_to_dict(candidates, self._top_k),
            )
            self._write_param_in_func_entry(node, param.arg, candidates)
            self._scope_assign(param.arg, candidates)

        # ── keyword-only params ───────────────────────────────────────────────
        for pos, param in enumerate(kwonly):
            usage = _extract_usage(param.arg, node.body)
            siblings = [(n, t) for (n, t) in sibling_info if n != param.arg]
            ctx = QueryContext(
                kind="param",
                identifier=param.arg,
                function_name=func_name,
                class_name=class_name,
                decorators=decorators,
                default_value_kind=_default_value_kind(kwonly_defaults.get(pos)),
                sibling_params=siblings,
                param_position=n_pos + pos,
                function_name_flags=name_flags,
                is_iterated=usage["is_iterated"],
                is_indexed=usage["is_indexed"],
                is_called=usage["is_called"],
                is_none_compared=usage["is_none_compared"],
                attribute_accesses=usage["attribute_accesses"],
            )
            candidates = self._retriever.query(ctx, top_k=self._top_k)
            self._write_retrieved(
                self._key(param.lineno, param.col_offset),
                _candidates_to_dict(candidates, self._top_k),
            )
            self._write_param_in_func_entry(node, param.arg, candidates)
            self._scope_assign(param.arg, candidates)

        # ── body ─────────────────────────────────────────────────────────────
        for stmt in node.body:
            self.visit(stmt)

        # ── return type ───────────────────────────────────────────────────────
        qname = (
            f"{self._relpath}:{class_name}.{func_name}"
            if class_name
            else f"{self._relpath}:{func_name}"
        )
        ret_ctx = QueryContext(
            kind="return",
            identifier=func_name,
            function_name=func_name,
            class_name=class_name,
            decorators=decorators,
            sibling_params=sibling_info,
            function_name_flags=name_flags,
        )
        ret_candidates = self._retriever.query(ret_ctx, top_k=self._top_k)
        func_key = self._key(node.lineno, node.col_offset + 4)
        self._write_retrieved(func_key, _candidates_to_dict(ret_candidates, self._top_k))
        if ret_candidates:
            self._return_candidates[qname] = ret_candidates

        self._scope_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node: ast.Assign) -> None:
        call_candidates = self._call_return_candidates(node.value)
        for target in node.targets:
            if isinstance(target, ast.Name):
                candidates = (
                    call_candidates
                    if call_candidates is not None
                    else self._retriever.query(
                        QueryContext(
                            kind="variable",
                            identifier=target.id,
                            class_name=self._class_stack[-1] if self._class_stack else None,
                        ),
                        top_k=self._top_k,
                    )
                )
                self._write_retrieved(
                    self._key(target.lineno, target.col_offset),
                    _candidates_to_dict(candidates, self._top_k),
                )
                self._scope_assign(target.id, candidates)
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name):
            name = node.target.id
            call_candidates = (
                self._call_return_candidates(node.value) if node.value else None
            )
            candidates = (
                call_candidates
                if call_candidates is not None
                else self._retriever.query(
                    QueryContext(
                        kind="variable",
                        identifier=name,
                        class_name=self._class_stack[-1] if self._class_stack else None,
                    ),
                    top_k=self._top_k,
                )
            )
            self._write_retrieved(
                self._key(node.target.lineno, node.target.col_offset),
                _candidates_to_dict(candidates, self._top_k),
            )
            self._scope_assign(name, candidates)
        if node.value:
            self.visit(node.value)

    def visit_Name(self, node: ast.Name) -> None:
        if not isinstance(node.ctx, ast.Load):
            return
        merged = self._merged_candidates(node.id)
        if merged:
            self._write_retrieved(self._key(node.lineno, node.col_offset), merged)

    def _call_return_candidates(
        self, value: Optional[ast.expr]
    ) -> Optional[list[TypeCandidate]]:
        if not isinstance(value, ast.Call):
            return None
        if not isinstance(value.func, ast.Name):
            return None
        fname = value.func.id
        class_name = self._class_stack[-1] if self._class_stack else None
        qname = (
            f"{self._relpath}:{class_name}.{fname}"
            if class_name
            else f"{self._relpath}:{fname}"
        )
        return self._return_candidates.get(qname)


def retrieve_file(
    py_path: Path,
    relpath: str,
    retriever: TypeRetriever,
    entries: dict[str, dict],
    top_k: int = 5,
) -> None:
    """Run the retrieval pass on one file, writing `retrieved` fields into `entries` in-place."""
    try:
        tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
    except (SyntaxError, Exception):
        return
    _RetrievalVisitor(relpath, retriever, entries, top_k).visit(tree)
