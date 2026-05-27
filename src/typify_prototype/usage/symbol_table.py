from __future__ import annotations
from dataclasses import dataclass, field
from .type_expr import TypeExpr, UNKNOWN


@dataclass
class Scope:
    parent: Scope | None = None
    _env: dict[str, TypeExpr] = field(default_factory=dict)
    _last: dict[str, TypeExpr] = field(default_factory=dict)

    def set(self, name: str, t: TypeExpr) -> None:
        self._env[name] = t

    def set_last(self, name: str, t: TypeExpr) -> None:
        self._last[name] = t

    def get(self, name: str) -> TypeExpr:
        if name in self._env:
            return self._env[name]
        if self.parent is not None:
            return self.parent.get(name)
        return UNKNOWN

    def get_last(self, name: str) -> TypeExpr:
        if name in self._last:
            return self._last[name]
        if self.parent is not None:
            return self.parent.get_last(name)
        return UNKNOWN


@dataclass
class ClassInfo:
    name: str
    fields: dict[str, TypeExpr] = field(default_factory=dict)


@dataclass
class FuncInfo:
    name: str
    params: list[str] = field(default_factory=list)
    return_type: TypeExpr = field(default_factory=lambda: UNKNOWN)


@dataclass
class ImportInfo:
    # from X import Y [as Z]: local_name → (source_relpath, original_name)
    names: dict[str, tuple[str, str]] = field(default_factory=dict)
    # import X [as Y]: local_alias → source_relpath
    modules: dict[str, str] = field(default_factory=dict)


@dataclass
class Registry:
    classes: dict[str, ClassInfo] = field(default_factory=dict)
    functions: dict[str, FuncInfo] = field(default_factory=dict)
    # dotted module name → relpath, e.g. "foo.bar" → "foo/bar.py"
    module_index: dict[str, str] = field(default_factory=dict)
    # relpath → ImportInfo for that file
    imports: dict[str, ImportInfo] = field(default_factory=dict)
    # relpath → {name: TypeExpr} for module-level variables
    module_vars: dict[str, dict[str, TypeExpr]] = field(default_factory=dict)
