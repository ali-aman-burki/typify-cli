"""
Type representations for the inference engine.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import FrozenSet, Tuple


# ---------------------------------------------------------------------------
# Primitive type atoms
# ---------------------------------------------------------------------------

class InferredType:
    """Base class for all inferred types."""

    def __or__(self, other: "InferredType") -> "InferredType":
        if self == other:
            return self
        return UnionType.of(self, other)

    def is_unknown(self) -> bool:
        return isinstance(self, UnknownType)

    def __repr__(self) -> str:
        return self.__str__()


@dataclass(frozen=True)
class PrimitiveType(InferredType):
    name: str  # 'int', 'float', 'str', 'bool', 'None', 'bytes'

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class UnknownType(InferredType):
    """We couldn't infer anything."""
    reason: str = ""

    def __str__(self) -> str:
        return "Unknown" + (f"({self.reason})" if self.reason else "")


@dataclass(frozen=True)
class AnyType(InferredType):
    """Explicitly 'any' — too dynamic to track."""
    def __str__(self) -> str:
        return "Any"


@dataclass(frozen=True)
class NoneType(InferredType):
    def __str__(self) -> str:
        return "None"


# ---------------------------------------------------------------------------
# Collection types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ListType(InferredType):
    element_type: InferredType = field(default_factory=lambda: UnknownType())

    def __str__(self) -> str:
        return f"list[{self.element_type}]"


@dataclass(frozen=True)
class TupleType(InferredType):
    element_types: Tuple[InferredType, ...] = ()
    homogeneous: bool = False          # True → tuple[T, ...]

    def __str__(self) -> str:
        if self.homogeneous and self.element_types:
            return f"tuple[{self.element_types[0]}, ...]"
        if not self.element_types:
            return "tuple[()]"
        inner = ", ".join(str(t) for t in self.element_types)
        return f"tuple[{inner}]"


@dataclass(frozen=True)
class SetType(InferredType):
    element_type: InferredType = field(default_factory=lambda: UnknownType())

    def __str__(self) -> str:
        return f"set[{self.element_type}]"


@dataclass(frozen=True)
class DictType(InferredType):
    key_type: InferredType = field(default_factory=lambda: UnknownType())
    value_type: InferredType = field(default_factory=lambda: UnknownType())

    def __str__(self) -> str:
        return f"dict[{self.key_type}, {self.value_type}]"


# ---------------------------------------------------------------------------
# Callable / class types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FunctionType(InferredType):
    param_types: Tuple[InferredType, ...] = ()
    return_type: InferredType = field(default_factory=lambda: UnknownType())
    name: str = ""

    def __str__(self) -> str:
        params = ", ".join(str(t) for t in self.param_types)
        return f"({params}) -> {self.return_type}"


@dataclass(frozen=True)
class ClassType(InferredType):
    name: str = ""
    module: str = ""

    def __str__(self) -> str:
        return f"{self.module}.{self.name}" if self.module else self.name


@dataclass(frozen=True)
class InstanceType(InferredType):
    class_name: str = ""
    module: str = ""

    def __str__(self) -> str:
        return f"{self.module}.{self.class_name}" if self.module else self.class_name


# ---------------------------------------------------------------------------
# Union / Optional
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class UnionType(InferredType):
    types: FrozenSet[InferredType] = field(default_factory=frozenset)

    @staticmethod
    def of(*types: InferredType) -> InferredType:
        flat: list[InferredType] = []
        for t in types:
            if isinstance(t, UnionType):
                flat.extend(t.types)
            else:
                flat.append(t)
        unique = frozenset(flat)
        if len(unique) == 1:
            return next(iter(unique))
        return UnionType(types=unique)

    def __str__(self) -> str:
        parts = sorted(str(t) for t in self.types)
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Singletons for convenience
# ---------------------------------------------------------------------------

INT   = PrimitiveType("int")
FLOAT = PrimitiveType("float")
STR   = PrimitiveType("str")
BOOL  = PrimitiveType("bool")
NONE  = NoneType()
BYTES = PrimitiveType("bytes")
ANY   = AnyType()
UNKNOWN = UnknownType()


def optional(t: InferredType) -> InferredType:
    return UnionType.of(t, NONE)


def merge_types(*types: InferredType) -> InferredType:
    """Merge a sequence of inferred types into one (union if different)."""
    valid = [t for t in types if not isinstance(t, UnknownType)]
    if not valid:
        return UNKNOWN
    result = valid[0]
    for t in valid[1:]:
        result = result | t
    return result
