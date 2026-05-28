from __future__ import annotations
from dataclasses import dataclass
import ast


@dataclass(frozen=True)
class TypeExpr:
    base: str
    args: tuple[TypeExpr, ...] = ()

    def __str__(self) -> str:
        if not self.args:
            return self.base
        return f"{self.base}[{', '.join(str(a) for a in self.args)}]"

    def __repr__(self) -> str:
        return f"TypeExpr({self!s})"


UNKNOWN = TypeExpr("Unknown")


def union(a: TypeExpr, b: TypeExpr) -> TypeExpr:
    if a == b:
        return a
    if a == UNKNOWN:
        return b
    if b == UNKNOWN:
        return a
    a_parts = _flatten_union(a)
    b_parts = _flatten_union(b)
    combined = list(a_parts)
    for p in b_parts:
        if p not in combined:
            combined.append(p)
    if len(combined) == 1:
        return combined[0]
    return TypeExpr("Union", tuple(sorted(combined, key=str)))


def _flatten_union(t: TypeExpr) -> list[TypeExpr]:
    if t.base == "Union":
        return list(t.args)
    return [t]


def from_annotation(node: ast.expr | None) -> TypeExpr | None:
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return TypeExpr(node.value)
        if node.value is None:
            return TypeExpr("None")
    if isinstance(node, ast.Name):
        return TypeExpr(node.id)
    if isinstance(node, ast.Attribute):
        return TypeExpr(_dotted_name(node))
    if isinstance(node, ast.Subscript):
        base = from_annotation(node.value)
        if base is None:
            return None
        if isinstance(node.slice, ast.Tuple):
            args = tuple(
                a for a in (from_annotation(e) for e in node.slice.elts)
                if a is not None
            )
        else:
            arg = from_annotation(node.slice)
            args = (arg,) if arg is not None else ()
        return TypeExpr(base.base, args)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        # PEP 604: X | Y union syntax
        left = from_annotation(node.left)
        right = from_annotation(node.right)
        if left and right:
            return union(left, right)
    return None


def _dotted_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted_name(node.value)}.{node.attr}"
    return "?"
