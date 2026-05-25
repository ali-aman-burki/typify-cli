from __future__ import annotations
import ast
from dataclasses import dataclass, field
from typing import Literal, Union

def _canon_base(name: str) -> str:
	lowered = name.lower()

	if lowered in {"none", "nonetype"}:
		return "None"

	builtin_map = {
		"int": "int",
		"str": "str",
		"text": "str",
		"bool": "bool",
		"float": "float",
		"complex": "complex",
		"bytes": "bytes",
		"dict": "dict",
		"list": "list",
		"tuple": "tuple",
		"set": "set",
		"frozenset": "frozenset",
	}
	if lowered in builtin_map:
		return builtin_map[lowered]

	return name


def _flatten_union_args(args: Union[tuple[TypeExpr, ...], list[TypeExpr]]) -> tuple[TypeExpr, ...]:
	flat: list[TypeExpr] = []

	def _recurse(a: TypeExpr):
		if a.base == "Union":
			for sub in a.args:
				_recurse(sub)
		else:
			flat.append(a)

	for a in args:
		_recurse(a)

	# Deduplicate by structural equality
	unique: dict[TypeExpr, None] = {}
	for a in flat:
		unique[a] = None
	return tuple(unique.keys())


def _attr_last_ident(node: ast.AST) -> str:
	if isinstance(node, ast.Attribute):
		return node.attr
	if isinstance(node, ast.Name):
		return node.id
	return ast.unparse(node) if hasattr(ast, "unparse") else "UNKNOWN"


def _slice_to_nodes(slice_node: ast.AST) -> list[ast.AST]:
	if isinstance(slice_node, ast.Tuple):
		return list(slice_node.elts)
	if isinstance(slice_node, ast.List):
		return list(slice_node.elts)
	return [slice_node]


def _expr_to_typeexpr(node: ast.AST) -> TypeExpr:
	if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
		left = _expr_to_typeexpr(node.left)
		right = _expr_to_typeexpr(node.right)
		return TypeExpr("Union", _flatten_union_args((left, right)))

	if isinstance(node, ast.Subscript):
		if isinstance(node.value, (ast.Name, ast.Attribute)):
			base = _attr_last_ident(node.value)
		else:
			base = ast.unparse(node.value) if hasattr(ast, "unparse") else "UNKNOWN"
		args = tuple(_expr_to_typeexpr(n) for n in _slice_to_nodes(node.slice))
		return TypeExpr(base, args)

	if isinstance(node, ast.Name):
		name = node.id
		if name in {"None", "NoneType"}:
			name = "None"
		return TypeExpr(name)

	if isinstance(node, ast.Attribute):
		return TypeExpr(_attr_last_ident(node))

	if isinstance(node, ast.Tuple):
		return TypeExpr("TupleLiteral", tuple(_expr_to_typeexpr(e) for e in node.elts))

	if isinstance(node, ast.List):
		return TypeExpr("ListLiteral", tuple(_expr_to_typeexpr(e) for e in node.elts))

	if isinstance(node, ast.Constant):
		if node.value is None:
			return TypeExpr("None")
		if node.value is Ellipsis:
			return TypeExpr("Ellipsis")
		if isinstance(node.value, str):
			try:
				return parse_typeexpr(node.value)
			except Exception:
				return TypeExpr(node.value)
		return TypeExpr(repr(node.value))

	try:
		return TypeExpr(ast.unparse(node))
	except Exception:
		return TypeExpr("UNKNOWN")


def parse_typeexpr(s: str) -> TypeExpr:
	txt = s.strip()
	if not txt:
		return TypeExpr("EMPTY")
	try:
		node = ast.parse(txt, mode="eval").body
		return _expr_to_typeexpr(node).canonical()
	except SyntaxError:
		if (txt.startswith("'") and txt.endswith("'")) or (txt.startswith('"') and txt.endswith('"')):
			try:
				node = ast.parse(txt[1:-1], mode="eval").body
				return _expr_to_typeexpr(node).canonical()
			except Exception:
				pass
		return TypeExpr(txt).canonical()


# ------------------------------------------------------------
# TypeExpr class
# ------------------------------------------------------------
@dataclass(frozen=True)
class TypeExpr:
	base: str
	args: tuple[TypeExpr, ...] = field(default_factory=tuple)

	def __str__(self) -> str:
		if not self.args:
			return self.base
		return f"{self.base}[{', '.join(map(str, self.args))}]"

	def canonical(self) -> TypeExpr:
		base = _canon_base(self.base)
		cargs = tuple(a.canonical() for a in self.args)

		# --- Collapse known wrappers ---
		if base in {"Annotated", "Final", "ClassVar", "Required", "NotRequired"} and len(cargs) >= 1:
			return cargs[0]

		# --- Optional[T] → Union[T, None] ---
		if base == "Optional" and len(cargs) == 1:
			return TypeExpr("Union", _flatten_union_args((cargs[0], TypeExpr("None"))))._union_sorted()

		# --- Flatten nested Unions (but don't absorb Any) ---
		if base == "Union":
			flat = _flatten_union_args(cargs)
			if len(flat) == 1:
				return flat[0]
			return TypeExpr("Union", flat)._union_sorted()

		# --- Callable canonicalization ---
		if base == "Callable" and len(cargs) == 2:
			params, ret = cargs
			if params.base in {"ListLiteral", "TupleLiteral"}:
				params = TypeExpr("Tuple", params.args)
			if (params.is_any() or params.base == "Ellipsis") and ret.is_any():
				return TypeExpr("Callable")
			return TypeExpr("Callable", (params, ret))

		# --- Simplify common container types ---
		container_like = {
			"list", "set", "frozenset", "tuple",
			"dict", "deque", "defaultdict",
			"Iterable", "Iterator", "Sequence",
			"Mapping", "MutableMapping", "Collection",
			"Container", "KeysView", "ValuesView", "ItemsView",
		}

		if base in container_like:
			if not cargs:
				return TypeExpr(base)
			if base == "dict":
				if len(cargs) == 2 and all(a.is_any() for a in cargs):
					return TypeExpr(base)
			elif all(a.is_any() for a in cargs):
				return TypeExpr(base)

		# --- Type[Any] → type ---
		if base == "Type" and len(cargs) == 1 and cargs[0].is_any():
			return TypeExpr("type")

		# --- Clean up leftover redundancies ---
		if base == "Any":
			return TypeExpr("Any")

		return TypeExpr(base, cargs)

	def _union_sorted(self) -> TypeExpr:
		if self.base != "Union":
			return self
		args = tuple(sorted(self.args, key=str))
		if len(args) == 1:
			return args[0]
		return TypeExpr("Union", args)

	def is_any(self) -> bool:
		return self.base == "Any" and not self.args


# ------------------------------------------------------------
# Matching utilities
# ------------------------------------------------------------
def exact_match(a: TypeExpr, b: TypeExpr) -> bool:
	a = a.canonical()
	b = b.canonical()

	if not base_match(a, b):
		return False

	if not a.args and b.args:
		return True

	if a.args and not b.args:
		return False

	if len(a.args) != len(b.args):
		return False

	return all(exact_match(x, y) for x, y in zip(a.args, b.args))


def base_match(a: TypeExpr, b: TypeExpr) -> bool:
	ab = a.base.lower()
	bb = b.base.lower()

	if ab in {"any", "object"}:
		return True

	if ab == "iterable" and bb in {"list", "tuple", "set", "frozenset", "dict", "str", "bytes"}:
		return True

	if ab == "sequence" and bb in {"list", "tuple", "str", "bytes"}:
		return True

	if ab == "collection" and bb in {"list", "tuple", "set", "frozenset", "dict", "str", "bytes"}:
		return True

	if ab in {"mapping", "dict"} and bb == "dict":
		return True

	if ab in {"number", "numeric"} and bb in {"int", "float", "complex"}:
		return True
	if ab == "float" and bb == "int":
		return True
	if ab == "complex" and bb in {"int", "float"}:
		return True

	if ab == "callable" and bb in {"function", "method"}:
		return True

	if ab == "hashable" and bb in {"int", "str", "float", "tuple", "frozenset", "bytes"}:
		return True

	if ab == "container" and bb in {"list", "tuple", "set", "frozenset", "dict", "str", "bytes"}:
		return True

	return ab == bb

# ------------------------------------------------------------
# Kind classification
# ------------------------------------------------------------

_KIND = Literal["generic", "simple", "user-defined"]

# Built-in, non-parametric "simple" bases (already canonicalized)
_SIMPLE_BUILTINS: set[str] = {
    "None", "Any", "object",
    "int", "str", "bool", "float", "complex", "bytes",
    "list", "tuple", "dict", "set", "frozenset",
    "type",
}

def classify_kind(te_or_str: Union[TypeExpr, str]) -> _KIND:
    """
    Classify a type into one of: "generic", "simple", "user-defined".
    Rules (priority order):
      1) If the (canonical) expression is parametric (has args) OR is a Union/Callable with args → "generic".
      2) Else if it's a built-in and *non-parametric* → "simple".
      3) Else → "user-defined".
    """
    te = parse_typeexpr(te_or_str) if isinstance(te_or_str, str) else te_or_str
    te = te.canonical()

    if te.args:
        return "generic"
    if te.base in {"Union"}:
        return "generic"
    if te.base == "Callable":
        return "simple" if not te.args else "generic"

    if te.base in _SIMPLE_BUILTINS:
        return "simple"

    return "user-defined"
