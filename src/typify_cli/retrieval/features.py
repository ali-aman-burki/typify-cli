"""
Feature extraction for type annotation sites.

For each annotated identifier in a Python file, we extract two tiers of context:
  Tier 1 (local, cheap): name, kind, default value, decorators, function name
                         conventions, sibling params
  Tier 2 (body analysis): attribute accesses, iteration/indexing/call usage patterns

All extraction is done under Python 3.11 AST semantics (parse with 3.11 target).
Files that fail to parse are silently skipped by the caller.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class AnnotationSite:
    """One extracted annotation site from a source file."""

    # --- identity ---
    kind: str                        # "param" | "return" | "variable"
    identifier: str                  # raw name of the annotated identifier
    annotated_type: str              # the type annotation as a string

    # --- tier 1 ---
    function_name: Optional[str]     # enclosing function/method name, if any
    class_name: Optional[str]        # enclosing class name, if any
    decorators: list[str] = field(default_factory=list)
    default_value_kind: Optional[str] = None   # "none_literal" | "empty_list" |
                                                # "empty_dict" | "numeric_zero" |
                                                # "string_literal" | "bool_literal" |
                                                # "other" | None (no default)
    sibling_params: list[tuple[str, Optional[str]]] = field(default_factory=list)
    # list of (param_name, annotated_type_str_or_None) for other params
    param_position: Optional[int] = None       # 0-based index in param list
    function_name_flags: list[str] = field(default_factory=list)
    # e.g. ["is_predicate", "dunder", "getter", "setter"]

    # --- tier 2 ---
    is_iterated: bool = False        # used as `for x in <ident>`
    is_indexed: bool = False         # used as `<ident>[...]`
    is_called: bool = False          # used as `<ident>(...)`
    is_none_compared: bool = False   # compared to None / used in `if ident`
    attribute_accesses: list[str] = field(default_factory=list)
    # e.g. ["append", "keys", "split"] — method/attr names accessed on ident

    # --- provenance ---
    source_file: str = ""
    line: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _annotation_to_str(node: Optional[ast.expr]) -> Optional[str]:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:
        return None


def _default_value_kind(node: Optional[ast.expr]) -> Optional[str]:
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        v = node.value
        if v is None:
            return "none_literal"
        if isinstance(v, bool):
            return "bool_literal"
        if isinstance(v, int) and v == 0:
            return "numeric_zero"
        if isinstance(v, (int, float)):
            return "numeric_literal"
        if isinstance(v, str):
            return "string_literal"
    if isinstance(node, ast.List) and not node.elts:
        return "empty_list"
    if isinstance(node, ast.Dict) and not node.keys:
        return "empty_dict"
    if isinstance(node, ast.Tuple) and not node.elts:
        return "empty_tuple"
    if isinstance(node, ast.Set) and not node.elts:
        return "empty_set"
    return "other"


def _function_name_flags(name: str) -> list[str]:
    flags = []
    if name.startswith("__") and name.endswith("__"):
        flags.append("dunder")
        if name == "__len__":
            flags.append("returns_int")
        elif name == "__bool__":
            flags.append("returns_bool")
        elif name == "__str__":
            flags.append("returns_str")
        elif name == "__init__":
            flags.append("constructor")
    if re.match(r'^is_|^has_|^can_|^should_|^was_|^will_', name):
        flags.append("predicate")
    if re.match(r'^get_|^fetch_|^load_|^read_|^find_', name):
        flags.append("getter")
    if re.match(r'^set_|^update_|^write_|^save_|^store_', name):
        flags.append("setter")
    if re.match(r'^to_|^as_|^convert_|^parse_|^format_', name):
        flags.append("converter")
    return flags


def _decorator_names(decorator_list: list[ast.expr]) -> list[str]:
    names = []
    for dec in decorator_list:
        if isinstance(dec, ast.Name):
            names.append(dec.id)
        elif isinstance(dec, ast.Attribute):
            names.append(dec.attr)
        elif isinstance(dec, ast.Call):
            if isinstance(dec.func, ast.Name):
                names.append(dec.func.id)
            elif isinstance(dec.func, ast.Attribute):
                names.append(dec.func.attr)
    return names


# ---------------------------------------------------------------------------
# Tier 2: body usage analysis
# ---------------------------------------------------------------------------

class _UsageVisitor(ast.NodeVisitor):
    def __init__(self, target: str):
        self.target = target
        self.is_iterated = False
        self.is_indexed = False
        self.is_called = False
        self.is_none_compared = False
        self.attribute_accesses: list[str] = []

    def visit_For(self, node: ast.For) -> None:
        if isinstance(node.iter, ast.Name) and node.iter.id == self.target:
            self.is_iterated = True
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        if isinstance(node.iter, ast.Name) and node.iter.id == self.target:
            self.is_iterated = True
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if isinstance(node.value, ast.Name) and node.value.id == self.target:
            self.is_indexed = True
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id == self.target:
            self.is_called = True
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.value, ast.Name) and node.value.id == self.target:
            self.attribute_accesses.append(node.attr)
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        left_is_target = isinstance(node.left, ast.Name) and node.left.id == self.target
        for op, comparator in zip(node.ops, node.comparators):
            if isinstance(comparator, ast.Constant) and comparator.value is None:
                if left_is_target or (
                    isinstance(comparator, ast.Name) and comparator.id == self.target
                ):
                    self.is_none_compared = True
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        test = node.test
        if isinstance(test, ast.Name) and test.id == self.target:
            self.is_none_compared = True
        elif isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            if isinstance(test.operand, ast.Name) and test.operand.id == self.target:
                self.is_none_compared = True
        self.generic_visit(node)


def _extract_usage(target: str, func_body: list[ast.stmt]) -> dict:
    visitor = _UsageVisitor(target)
    for stmt in func_body:
        visitor.visit(stmt)
    return {
        "is_iterated": visitor.is_iterated,
        "is_indexed": visitor.is_indexed,
        "is_called": visitor.is_called,
        "is_none_compared": visitor.is_none_compared,
        "attribute_accesses": list(dict.fromkeys(visitor.attribute_accesses)),
    }


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------

class AnnotationExtractor(ast.NodeVisitor):
    def __init__(self, source_file: str):
        self.source_file = source_file
        self.sites: list[AnnotationSite] = []
        self._class_stack: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._process_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._process_function(node)

    def _process_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        class_name = self._class_stack[-1] if self._class_stack else None
        func_name = node.name
        decorators = _decorator_names(node.decorator_list)
        name_flags = _function_name_flags(func_name)

        args = node.args
        all_positional = args.posonlyargs + args.args
        n_pos = len(all_positional)
        n_defaults = len(args.defaults)
        defaults_map: dict[int, ast.expr] = {}
        for i, d in enumerate(args.defaults):
            idx = n_pos - n_defaults + i
            defaults_map[idx] = d

        kwonly_defaults_map: dict[int, ast.expr] = {}
        for i, d in enumerate(args.kw_defaults):
            if d is not None:
                kwonly_defaults_map[i] = d

        sibling_info: list[tuple[str, Optional[str]]] = []
        for p in all_positional:
            sibling_info.append((p.arg, _annotation_to_str(p.annotation)))
        for p in args.kwonlyargs:
            sibling_info.append((p.arg, _annotation_to_str(p.annotation)))

        for pos, param in enumerate(all_positional):
            ann_str = _annotation_to_str(param.annotation)
            if ann_str is None:
                continue
            default_node = defaults_map.get(pos)
            siblings = [(n, t) for i, (n, t) in enumerate(sibling_info) if i != pos]
            usage = _extract_usage(param.arg, node.body)
            site = AnnotationSite(
                kind="param",
                identifier=param.arg,
                annotated_type=ann_str,
                function_name=func_name,
                class_name=class_name,
                decorators=decorators,
                default_value_kind=_default_value_kind(default_node),
                sibling_params=siblings,
                param_position=pos,
                function_name_flags=name_flags,
                is_iterated=usage["is_iterated"],
                is_indexed=usage["is_indexed"],
                is_called=usage["is_called"],
                is_none_compared=usage["is_none_compared"],
                attribute_accesses=usage["attribute_accesses"],
                source_file=self.source_file,
                line=param.col_offset,
            )
            self.sites.append(site)

        for pos, param in enumerate(args.kwonlyargs):
            ann_str = _annotation_to_str(param.annotation)
            if ann_str is None:
                continue
            default_node = kwonly_defaults_map.get(pos)
            siblings = [(n, t) for i, (n, t) in enumerate(sibling_info)
                        if sibling_info[i][0] != param.arg]
            usage = _extract_usage(param.arg, node.body)
            site = AnnotationSite(
                kind="param",
                identifier=param.arg,
                annotated_type=ann_str,
                function_name=func_name,
                class_name=class_name,
                decorators=decorators,
                default_value_kind=_default_value_kind(default_node),
                sibling_params=siblings,
                param_position=len(all_positional) + pos,
                function_name_flags=name_flags,
                is_iterated=usage["is_iterated"],
                is_indexed=usage["is_indexed"],
                is_called=usage["is_called"],
                is_none_compared=usage["is_none_compared"],
                attribute_accesses=usage["attribute_accesses"],
                source_file=self.source_file,
                line=param.col_offset,
            )
            self.sites.append(site)

        ret_str = _annotation_to_str(node.returns)
        if ret_str is not None:
            site = AnnotationSite(
                kind="return",
                identifier=func_name,
                annotated_type=ret_str,
                function_name=func_name,
                class_name=class_name,
                decorators=decorators,
                sibling_params=sibling_info,
                function_name_flags=name_flags,
                source_file=self.source_file,
                line=node.lineno,
            )
            self.sites.append(site)

        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        ann_str = _annotation_to_str(node.annotation)
        if ann_str is None:
            self.generic_visit(node)
            return

        if isinstance(node.target, ast.Name):
            ident = node.target.id
        elif isinstance(node.target, ast.Attribute):
            ident = node.target.attr
        else:
            self.generic_visit(node)
            return

        class_name = self._class_stack[-1] if self._class_stack else None

        site = AnnotationSite(
            kind="variable",
            identifier=ident,
            annotated_type=ann_str,
            function_name=None,
            class_name=class_name,
            source_file=self.source_file,
            line=node.lineno,
        )
        self.sites.append(site)
        self.generic_visit(node)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_from_source(source: str, source_file: str = "<unknown>") -> list[AnnotationSite]:
    """Parse `source` as Python and extract all annotation sites."""
    try:
        tree = ast.parse(source, filename=source_file, type_comments=False)
    except SyntaxError:
        return []
    except Exception:
        return []

    extractor = AnnotationExtractor(source_file=source_file)
    extractor.visit(tree)
    return extractor.sites


def extract_from_file(path: str) -> list[AnnotationSite]:
    """Read a .py file and extract annotation sites. Silently skips on any error."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            source = f.read()
    except Exception:
        return []
    return extract_from_source(source, source_file=path)
