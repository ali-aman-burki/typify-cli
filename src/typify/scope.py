"""
Scope / symbol-table management for the type inference engine.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Iterator

from .types import InferredType, UNKNOWN


class ScopeKind(Enum):
    MODULE   = auto()
    CLASS    = auto()
    FUNCTION = auto()
    LAMBDA   = auto()


@dataclass
class Symbol:
    name: str
    inferred_type: InferredType = field(default_factory=lambda: UNKNOWN)
    # Where defined (filename, lineno, col_offset)
    defined_at: Optional[tuple] = None
    # Assignments seen (for tracking multiple writes)
    assignment_types: List[InferredType] = field(default_factory=list)

    def update(self, t: InferredType) -> None:
        self.assignment_types.append(t)
        from .types import merge_types, UNKNOWN
        self.inferred_type = merge_types(*self.assignment_types)

    def __repr__(self) -> str:
        return f"Symbol({self.name!r}: {self.inferred_type})"


class Scope:
    def __init__(
        self,
        kind: ScopeKind,
        name: str = "",
        parent: Optional["Scope"] = None,
    ) -> None:
        self.kind = kind
        self.name = name
        self.parent = parent
        self._symbols: Dict[str, Symbol] = {}

    # ------------------------------------------------------------------
    # Symbol access
    # ------------------------------------------------------------------

    def define(self, name: str, t: InferredType, location=None) -> Symbol:
        if name not in self._symbols:
            self._symbols[name] = Symbol(name=name, defined_at=location)
        self._symbols[name].update(t)
        return self._symbols[name]

    def lookup_local(self, name: str) -> Optional[Symbol]:
        return self._symbols.get(name)

    def lookup(self, name: str) -> Optional[Symbol]:
        """Walk up the scope chain."""
        scope: Optional[Scope] = self
        while scope is not None:
            sym = scope.lookup_local(name)
            if sym is not None:
                return sym
            scope = scope.parent
        return None

    def all_symbols(self) -> Iterator[Symbol]:
        yield from self._symbols.values()

    @property
    def qualified_name(self) -> str:
        parts = []
        scope: Optional[Scope] = self
        while scope is not None:
            if scope.name:
                parts.append(scope.name)
            scope = scope.parent
        return ".".join(reversed(parts))

    def __repr__(self) -> str:
        return f"Scope({self.kind.name}, {self.name!r}, syms={list(self._symbols)})"


class ScopeStack:
    """Manages a stack of scopes during AST traversal."""

    def __init__(self) -> None:
        self._stack: List[Scope] = []

    def push(self, kind: ScopeKind, name: str = "") -> Scope:
        parent = self._stack[-1] if self._stack else None
        scope = Scope(kind=kind, name=name, parent=parent)
        self._stack.append(scope)
        return scope

    def pop(self) -> Scope:
        return self._stack.pop()

    @property
    def current(self) -> Scope:
        return self._stack[-1]

    def define(self, name: str, t: InferredType, location=None) -> Symbol:
        return self.current.define(name, t, location)

    def lookup(self, name: str) -> Optional[Symbol]:
        return self.current.lookup(name)

    def all_scopes(self) -> List[Scope]:
        return list(self._stack)

    def __len__(self) -> int:
        return len(self._stack)
