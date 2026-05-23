"""
Core type inference engine.

Performs multi-pass AST analysis:
  Pass 1 – literal / constant inference
  Pass 2 – name / assignment propagation
  Pass 3 – binary / unary operation inference
  Pass 4 – builtin call inference
  Pass 5 – return-type inference for functions
  Pass 6 – attribute inference for known classes
"""
from __future__ import annotations

import ast
from typing import Dict, List, Optional, Tuple

from .types import (
    InferredType, UNKNOWN, ANY, INT, FLOAT, STR, BOOL, NONE, BYTES,
    ListType, TupleType, SetType, DictType,
    FunctionType, ClassType, InstanceType,
    UnionType, NoneType, PrimitiveType,
    merge_types, optional,
)
from .scope import ScopeKind, ScopeStack, Symbol


# ---------------------------------------------------------------------------
# Builtin function return-type table
# ---------------------------------------------------------------------------

_BUILTIN_RETURNS: Dict[str, InferredType] = {
    # numeric
    "int": INT, "float": FLOAT, "complex": PrimitiveType("complex"),
    "abs": UNKNOWN,       # depends on arg; refined below
    "round": FLOAT,
    "pow": FLOAT,
    "divmod": TupleType((INT, INT)),
    "sum": INT,
    "min": UNKNOWN, "max": UNKNOWN,
    # string / bytes
    "str": STR, "repr": STR, "chr": STR, "hex": STR, "oct": STR, "bin": STR,
    "bytes": BYTES, "bytearray": PrimitiveType("bytearray"),
    "ord": INT,
    "format": STR,
    # collections
    "list": ListType(), "tuple": TupleType(), "set": SetType(), "dict": DictType(),
    "frozenset": PrimitiveType("frozenset"),
    "sorted": ListType(), "reversed": UNKNOWN,
    "enumerate": UNKNOWN, "zip": UNKNOWN, "map": UNKNOWN, "filter": UNKNOWN,
    "range": PrimitiveType("range"),
    # meta
    "len": INT, "id": INT, "hash": INT,
    "bool": BOOL,
    "callable": BOOL, "isinstance": BOOL, "issubclass": BOOL, "hasattr": BOOL,
    "getattr": UNKNOWN, "setattr": NONE, "delattr": NONE,
    "type": ClassType("type"),
    "vars": DictType(STR, UNKNOWN), "dir": ListType(STR),
    "input": STR,
    "open": PrimitiveType("IO"),
    "print": NONE, "exec": NONE, "eval": UNKNOWN,
    "iter": UNKNOWN, "next": UNKNOWN,
    "super": UNKNOWN,
    "object": InstanceType("object"),
}

# String method → return type
_STR_METHODS: Dict[str, InferredType] = {
    "upper": STR, "lower": STR, "strip": STR, "lstrip": STR, "rstrip": STR,
    "capitalize": STR, "title": STR, "swapcase": STR,
    "replace": STR, "encode": BYTES,
    "split": ListType(STR), "rsplit": ListType(STR), "splitlines": ListType(STR),
    "join": STR,
    "find": INT, "rfind": INT, "index": INT, "rindex": INT, "count": INT,
    "startswith": BOOL, "endswith": BOOL, "isdigit": BOOL, "isalpha": BOOL,
    "isalnum": BOOL, "isspace": BOOL, "islower": BOOL, "isupper": BOOL,
    "format": STR, "format_map": STR,
    "zfill": STR, "ljust": STR, "rjust": STR, "center": STR,
}

# List method → return type
_LIST_METHODS: Dict[str, InferredType] = {
    "append": NONE, "extend": NONE, "insert": NONE, "remove": NONE,
    "pop": UNKNOWN, "clear": NONE, "reverse": NONE, "sort": NONE,
    "copy": ListType(), "count": INT, "index": INT,
}

# Dict method → return type
_DICT_METHODS: Dict[str, InferredType] = {
    "keys": UNKNOWN, "values": UNKNOWN, "items": UNKNOWN,
    "get": UNKNOWN, "pop": UNKNOWN, "popitem": TupleType(),
    "update": NONE, "clear": NONE, "copy": DictType(),
    "setdefault": UNKNOWN,
}


# ---------------------------------------------------------------------------
# Arithmetic / comparison type rules
# ---------------------------------------------------------------------------

def _binop_type(left: InferredType, op: ast.operator, right: InferredType) -> InferredType:
    """Infer the result type of a binary operation."""
    l, r = left, right

    # Numeric promotions
    if isinstance(op, (ast.Add, ast.Sub, ast.Mult, ast.Pow, ast.FloorDiv, ast.Mod)):
        if l == INT and r == INT:
            return INT
        if {l, r} <= {INT, FLOAT}:
            return FLOAT
        if isinstance(op, ast.Add) and l == STR and r == STR:
            return STR
        if isinstance(op, ast.Mult):
            if l == STR and r == INT:
                return STR
            if l == INT and r == STR:
                return STR
    if isinstance(op, ast.Div):
        if {l, r} <= {INT, FLOAT}:
            return FLOAT

    # Bitwise ops → int
    if isinstance(op, (ast.BitAnd, ast.BitOr, ast.BitXor, ast.LShift, ast.RShift)):
        if l == INT and r == INT:
            return INT

    return UNKNOWN


def _cmpop_type(_left, _op, _right) -> InferredType:
    return BOOL


def _unaryop_type(op: ast.unaryop, operand: InferredType) -> InferredType:
    if isinstance(op, ast.Not):
        return BOOL
    if isinstance(op, ast.USub):
        if operand in (INT, FLOAT):
            return operand
    if isinstance(op, ast.Invert):
        return INT
    if isinstance(op, ast.UAdd):
        return operand
    return UNKNOWN


# ---------------------------------------------------------------------------
# Main inference visitor
# ---------------------------------------------------------------------------

class InferenceResult:
    """Holds results for a single module."""

    def __init__(self, filename: str) -> None:
        self.filename = filename
        # flat list of (qualified_name, symbol)
        self.bindings: List[Tuple[str, Symbol]] = []
        # function return types: qualified_name → type
        self.function_returns: Dict[str, InferredType] = {}
        # class attribute types: ClassName.attr → type
        self.class_attrs: Dict[str, InferredType] = {}


class TypeInferenceVisitor(ast.NodeVisitor):
    """
    Single-file type inference via AST traversal.
    """

    def __init__(self, filename: str, module_name: str = "") -> None:
        self.filename = filename
        self.module_name = module_name
        self.scopes = ScopeStack()
        self.result = InferenceResult(filename)
        # pending function defs: name → (node, scope snapshot)
        self._current_class: Optional[str] = None
        self._current_function: Optional[str] = None
        # collect return expressions per function
        self._return_types_stack: List[List[InferredType]] = []

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def infer(self, source: str) -> InferenceResult:
        tree = ast.parse(source, filename=self.filename)
        self.scopes.push(ScopeKind.MODULE, self.module_name)
        self.visit(tree)
        self.scopes.pop()
        return self.result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _loc(self, node: ast.AST):
        return (self.filename, getattr(node, "lineno", None))

    def _define(self, name: str, t: InferredType, node: ast.AST) -> Symbol:
        sym = self.scopes.define(name, t, self._loc(node))
        qname = self._qualified(name)
        self.result.bindings.append((qname, sym))
        return sym

    def _qualified(self, name: str) -> str:
        parts = []
        if self._current_class:
            parts.append(self._current_class)
        if self._current_function:
            parts.append(self._current_function)
        parts.append(name)
        return ".".join(parts)

    def _lookup_type(self, name: str) -> InferredType:
        sym = self.scopes.lookup(name)
        return sym.inferred_type if sym else UNKNOWN

    # ------------------------------------------------------------------
    # Expression inference
    # ------------------------------------------------------------------

    def infer_expr(self, node: ast.expr) -> InferredType:  # noqa: C901
        if node is None:
            return UNKNOWN

        # --- Literals ---
        if isinstance(node, ast.Constant):
            return self._infer_constant(node)

        # --- Name ---
        if isinstance(node, ast.Name):
            return self._lookup_type(node.id)

        # --- f-string ---
        if isinstance(node, ast.JoinedStr):
            return STR

        # --- Binary op ---
        if isinstance(node, ast.BinOp):
            l = self.infer_expr(node.left)
            r = self.infer_expr(node.right)
            return _binop_type(l, node.op, r)

        # --- Unary op ---
        if isinstance(node, ast.UnaryOp):
            operand = self.infer_expr(node.operand)
            return _unaryop_type(node.op, operand)

        # --- Boolean op (and / or) ---
        if isinstance(node, ast.BoolOp):
            types = [self.infer_expr(v) for v in node.values]
            return merge_types(*types)

        # --- Compare ---
        if isinstance(node, ast.Compare):
            return BOOL

        # --- Conditional expr (ternary) ---
        if isinstance(node, ast.IfExp):
            t1 = self.infer_expr(node.body)
            t2 = self.infer_expr(node.orelse)
            return merge_types(t1, t2)

        # --- Collections ---
        if isinstance(node, ast.List):
            elem = merge_types(*[self.infer_expr(e) for e in node.elts]) if node.elts else UNKNOWN
            return ListType(elem)

        if isinstance(node, ast.Tuple):
            elems = tuple(self.infer_expr(e) for e in node.elts)
            return TupleType(elems)

        if isinstance(node, ast.Set):
            elem = merge_types(*[self.infer_expr(e) for e in node.elts]) if node.elts else UNKNOWN
            return SetType(elem)

        if isinstance(node, ast.Dict):
            keys = [self.infer_expr(k) for k in node.keys if k is not None]
            vals = [self.infer_expr(v) for v in node.values]
            k_type = merge_types(*keys) if keys else UNKNOWN
            v_type = merge_types(*vals) if vals else UNKNOWN
            return DictType(k_type, v_type)

        # --- Subscript ---
        if isinstance(node, ast.Subscript):
            container = self.infer_expr(node.value)
            if isinstance(container, ListType):
                return container.element_type
            if isinstance(container, DictType):
                return container.value_type
            if isinstance(container, TupleType) and container.element_types:
                # Try to resolve index
                if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, int):
                    idx = node.slice.value
                    if 0 <= idx < len(container.element_types):
                        return container.element_types[idx]
                return merge_types(*container.element_types)
            return UNKNOWN

        # --- Attribute access ---
        if isinstance(node, ast.Attribute):
            return self._infer_attribute(node)

        # --- Call ---
        if isinstance(node, ast.Call):
            return self._infer_call(node)

        # --- Starred ---
        if isinstance(node, ast.Starred):
            return self.infer_expr(node.value)

        # --- Lambda ---
        if isinstance(node, ast.Lambda):
            return FunctionType()

        return UNKNOWN

    def _infer_constant(self, node: ast.Constant) -> InferredType:
        v = node.value
        if isinstance(v, bool):   return BOOL
        if isinstance(v, int):    return INT
        if isinstance(v, float):  return FLOAT
        if isinstance(v, str):    return STR
        if isinstance(v, bytes):  return BYTES
        if v is None:             return NONE
        if isinstance(v, complex): return PrimitiveType("complex")
        return UNKNOWN

    def _infer_attribute(self, node: ast.Attribute) -> InferredType:
        obj_type = self.infer_expr(node.value)
        attr = node.attr

        if obj_type == STR:
            return _STR_METHODS.get(attr, UNKNOWN)
        if isinstance(obj_type, ListType):
            return _LIST_METHODS.get(attr, UNKNOWN)
        if isinstance(obj_type, DictType):
            return _DICT_METHODS.get(attr, UNKNOWN)

        # Instance attribute lookup
        if isinstance(obj_type, InstanceType):
            key = f"{obj_type.class_name}.{attr}"
            return self.result.class_attrs.get(key, UNKNOWN)

        # self.x inside a class method
        if isinstance(node.value, ast.Name) and node.value.id == "self":
            if self._current_class:
                key = f"{self._current_class}.{attr}"
                return self.result.class_attrs.get(key, UNKNOWN)

        return UNKNOWN

    def _infer_call(self, node: ast.Call) -> InferredType:  # noqa: C901
        func = node.func

        # Simple name call: len(), str(), etc.
        if isinstance(func, ast.Name):
            name = func.id
            # Check builtin table
            if name in _BUILTIN_RETURNS:
                t = _BUILTIN_RETURNS[name]
                # Refine abs() based on arg type
                if name == "abs" and node.args:
                    arg_t = self.infer_expr(node.args[0])
                    return arg_t if arg_t in (INT, FLOAT) else UNKNOWN
                # min/max: return type of first arg
                if name in ("min", "max") and node.args:
                    return self.infer_expr(node.args[0])
                return t

            # Known user-defined function return type
            sym = self.scopes.lookup(name)
            if sym and isinstance(sym.inferred_type, FunctionType):
                return sym.inferred_type.return_type

            # Calling a class → produces an instance
            if sym and isinstance(sym.inferred_type, ClassType):
                return InstanceType(class_name=sym.inferred_type.name,
                                    module=sym.inferred_type.module)
            # Unknown class call heuristic: CapitalCase → instance
            if name[0].isupper():
                return InstanceType(class_name=name, module=self.module_name)

            return UNKNOWN

        # Method call: obj.method(...)
        if isinstance(func, ast.Attribute):
            obj_type = self.infer_expr(func.value)
            method = func.attr

            if obj_type == STR:
                return _STR_METHODS.get(method, UNKNOWN)
            if isinstance(obj_type, ListType):
                if method == "pop":
                    return obj_type.element_type
                return _LIST_METHODS.get(method, UNKNOWN)
            if isinstance(obj_type, DictType):
                if method == "keys":
                    return ListType(obj_type.key_type)
                if method == "values":
                    return ListType(obj_type.value_type)
                if method == "items":
                    return ListType(TupleType((obj_type.key_type, obj_type.value_type)))
                if method == "get":
                    return optional(obj_type.value_type)
                return _DICT_METHODS.get(method, UNKNOWN)

            # Instance method: look up recorded function return type
            if isinstance(obj_type, InstanceType):
                qname = f"{obj_type.class_name}.{method}"
                if qname in self.result.function_returns:
                    return self.result.function_returns[qname]

        return UNKNOWN

    # ------------------------------------------------------------------
    # Statement visitors
    # ------------------------------------------------------------------

    def visit_Assign(self, node: ast.Assign) -> None:
        value_type = self.infer_expr(node.value)

        for target in node.targets:
            self._assign_target(target, value_type, node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        # Ignore annotation; infer from value
        if node.value is not None:
            value_type = self.infer_expr(node.value)
            self._assign_target(node.target, value_type, node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        # e.g. x += 1
        current = self.infer_expr(node.target)
        rhs = self.infer_expr(node.value)
        result = _binop_type(current, node.op, rhs)
        if result.is_unknown():
            result = current  # keep current best guess
        self._assign_target(node.target, result, node)

    def _assign_target(self, target: ast.expr, value_type: InferredType, node: ast.AST) -> None:
        if isinstance(target, ast.Name):
            self._define(target.id, value_type, node)

        elif isinstance(target, ast.Tuple) or isinstance(target, ast.List):
            # Unpack
            if isinstance(value_type, TupleType) and value_type.element_types:
                for i, elt in enumerate(target.elts):
                    t = (value_type.element_types[i]
                         if i < len(value_type.element_types) else UNKNOWN)
                    self._assign_target(elt, t, node)
            else:
                for elt in target.elts:
                    self._assign_target(elt, UNKNOWN, node)

        elif isinstance(target, ast.Attribute):
            # self.x = ...
            if (isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                    and self._current_class):
                key = f"{self._current_class}.{target.attr}"
                self.result.class_attrs[key] = merge_types(
                    self.result.class_attrs.get(key, UNKNOWN),
                    value_type,
                )

    # ------------------------------------------------------------------
    # For loops
    # ------------------------------------------------------------------

    def visit_For(self, node: ast.For) -> None:
        iter_type = self.infer_expr(node.iter)
        elem_type = UNKNOWN
        if isinstance(iter_type, ListType):
            elem_type = iter_type.element_type
        elif isinstance(iter_type, SetType):
            elem_type = iter_type.element_type
        elif isinstance(iter_type, TupleType) and iter_type.element_types:
            elem_type = merge_types(*iter_type.element_types)
        elif isinstance(iter_type, DictType):
            elem_type = iter_type.key_type
        elif iter_type == STR:
            elem_type = STR

        self._assign_target(node.target, elem_type, node)
        self.generic_visit(node)

    # ------------------------------------------------------------------
    # With statement
    # ------------------------------------------------------------------

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            if item.optional_vars is not None:
                ctx_type = self.infer_expr(item.context_expr)
                self._assign_target(item.optional_vars, ctx_type, node)
        self.generic_visit(node)

    # ------------------------------------------------------------------
    # Function definitions
    # ------------------------------------------------------------------

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node) -> None:
        func_name = node.name
        parent_class = self._current_class
        parent_func = self._current_function

        qname = f"{parent_class}.{func_name}" if parent_class else func_name

        # Push scope
        self.scopes.push(ScopeKind.FUNCTION, func_name)
        self._current_function = func_name
        self._return_types_stack.append([])

        # Define parameters as Unknown (no annotations used)
        for arg in node.args.args:
            if arg.arg != "self":
                self._define(arg.arg, UNKNOWN, node)

        # Visit body
        self.generic_visit(node)

        # Collect return types
        return_types = self._return_types_stack.pop()
        if not return_types:
            inferred_return = NONE
        else:
            inferred_return = merge_types(*return_types)

        self._current_function = parent_func

        self.scopes.pop()

        # Record function return type
        self.result.function_returns[qname] = inferred_return

        # Define name in outer scope
        func_type = FunctionType(
            param_types=tuple(UNKNOWN for a in node.args.args if a.arg != "self"),
            return_type=inferred_return,
            name=qname,
        )
        self._define(func_name, func_type, node)

    def visit_Return(self, node: ast.Return) -> None:
        if self._return_types_stack:
            t = self.infer_expr(node.value) if node.value else NONE
            self._return_types_stack[-1].append(t)

    # ------------------------------------------------------------------
    # Class definitions
    # ------------------------------------------------------------------

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        class_name = node.name
        parent_class = self._current_class

        # Register class type
        cls_type = ClassType(name=class_name, module=self.module_name)
        self._define(class_name, cls_type, node)

        self.scopes.push(ScopeKind.CLASS, class_name)
        self._current_class = class_name

        for child in node.body:
            self.visit(child)

        self._current_class = parent_class
        self.scopes.pop()

    # ------------------------------------------------------------------
    # Import (record names as Any so lookups don't fail)
    # ------------------------------------------------------------------

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.asname if alias.asname else alias.name.split(".")[0]
            self._define(name, ANY, node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            name = alias.asname if alias.asname else alias.name
            self._define(name, ANY, node)
