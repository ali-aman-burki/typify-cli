import ast

from typing import Union, Optional
from pathlib import Path

from typify_prototype.preprocessing.instance_utils import Instance
from typify_prototype.preprocessing.module_meta import ModuleMeta
from typify_prototype.preprocessing.core import GlobalContext
from typify_prototype.preprocessing.symbol_table import Module, Package


def _add_unique(lst: list[ModuleMeta], item: ModuleMeta) -> None:
    if item not in lst:
        lst.append(item)


class DependencyUtils:

    @staticmethod
    def to_absolute_name(module_table: Module, name: Optional[str], level: int = 0) -> str:
        level = max(0, level)

        if level == 0:
            base_fqn = name or ""
        else:
            current_fqn = module_table.fqn
            parts = current_fqn.split(".")
            level = min(level, len(parts))
            base_parts = parts[:len(parts) - level]
            if name:
                base_parts.extend(name.split("."))
            base_fqn = ".".join(base_parts)

        return base_fqn

    @staticmethod
    def resolve_module_objects(
        defkey: tuple[Module, tuple[int, int]],
        name: Optional[str],
        level: int = 0
    ) -> list[Instance]:

        fqn = DependencyUtils.to_absolute_name(defkey[0], name, level)
        for lib in GlobalContext.libs.values():
            if fqn in lib.fqn_map:
                chain = lib.fqn_map[fqn]

                if all(table.fqn in GlobalContext.sysmodules for table in chain):
                    return [GlobalContext.sysmodules[table.fqn] for table in chain]

                modules = []
                if chain[0].fqn not in GlobalContext.sysmodules:
                    break
                current_object = GlobalContext.sysmodules[chain[0].fqn]
                modules.append(current_object)

                for table in chain[1:]:
                    if table.fqn in GlobalContext.sysmodules:
                        current_object = GlobalContext.sysmodules[table.fqn]
                        modules.append(current_object)

                return modules

        return []


class GraphBuilder:

    @staticmethod
    def initialize_globals():
        for lib in GlobalContext.libs.values():
            GlobalContext.meta_map.update(lib.meta_map)
            GlobalContext.sysmodules.update(lib.sysmodules)

    @staticmethod
    def _recompute_for_metas(metas: list[ModuleMeta]):
        builtins = GlobalContext.inference.get("builtins")
        for m in metas:
            GlobalContext.dependency_graph[m] = []
            if builtins:
                _add_unique(GlobalContext.dependency_graph[m], builtins)
            try:
                DependencyTracker(m).visit(m.tree)
            except (RecursionError, UnicodeError):
                continue

    @staticmethod
    def build_graph_all():
        GlobalContext.meta_map.clear()
        GlobalContext.sysmodules.clear()
        GlobalContext.dependency_graph.clear()

        GraphBuilder.initialize_globals()

        for lib in GlobalContext.libs.values():
            GraphBuilder._recompute_for_metas(list(lib.meta_map.values()))


class DependencyTracker(ast.NodeVisitor):
    def __init__(self, module_meta: ModuleMeta):
        self.module_meta = module_meta
        self.module_table = module_meta.table
        self.in_function = 0

        GlobalContext.dependency_graph[self.module_meta] = [GlobalContext.inference["builtins"]]

    def as_module_metas(self, modules: list[Module]) -> list[ModuleMeta]:
        return [GlobalContext.meta_map[table] for table in modules if table in GlobalContext.meta_map]

    def filter_chain(self, chain: list[Union[Module, Package]]):
        result = []
        for table in chain:
            if isinstance(table, Package):
                result.append(table.modules["__init__"])
            else:
                result.append(table)
        return result

    def resolve_fqn_chain(self, name: Optional[str], level: int = 0) -> list[Union[Module, Package]]:
        base_fqn = DependencyUtils.to_absolute_name(self.module_table, name, level)

        for lib in GlobalContext.libs.values():
            if base_fqn in lib.fqn_map:
                chain = lib.fqn_map[base_fqn]
                metas = self.as_module_metas(self.filter_chain(chain))
                for mm in metas:
                    _add_unique(GlobalContext.dependency_graph[self.module_meta], mm)
                return chain

        return []

    def visit_Import(self, node):
        if self.in_function:
            return
        for alias in node.names:
            self.resolve_fqn_chain(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if not self.in_function:
            names = {alias.name for alias in node.names if alias.name != "*"}
            chain = self.resolve_fqn_chain(node.module, node.level)
            if chain:
                endpoint = chain[-1]
                for name in names:
                    if isinstance(endpoint, Package):
                        if name in endpoint.packages:
                            self.resolve_fqn_chain(endpoint.packages[name].fqn)
                        elif name in endpoint.modules:
                            self.resolve_fqn_chain(endpoint.modules[name].fqn)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        self.in_function += 1
        self.generic_visit(node)
        self.in_function -= 1
