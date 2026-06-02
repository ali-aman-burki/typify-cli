import ast
import json

from typing import Union, Optional
from pathlib import Path

from ..utils.progbar import ProgressBar
from .instance_utils import Instance
from .module_meta import ModuleMeta
from .core import GlobalContext
from .symbol_table import (
	Module, 
	Package
)

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

				if chain[0].fqn not in GlobalContext.sysmodules: break
				
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
		from ..utils.logging import logger
		logger.debug(f"{logger.emoji_map['init']} [Cache] Initializing globals from libraries")
		for lib in GlobalContext.libs.values():
			GlobalContext.meta_map.update(lib.meta_map)
			GlobalContext.sysmodules.update(lib.sysmodules)

	@staticmethod
	def _dep_cache_file_for(lib) -> Optional[Path]:
		from ..utils.caching import GlobalCache
		lcache = GlobalCache.libs_cache.get(lib.src)
		if lcache is None:
			return None
		return lcache.lib_dir / "deps.json"

	def _serialize_edges_for(lib) -> dict[str, list[str]]:
		edges: dict[str, list[str]] = {}
		lib_paths = {Path(m.src).resolve() for m in lib.meta_map.values()}

		for from_meta, tos in GlobalContext.dependency_graph.items():
			if Path(from_meta.src).resolve() not in lib_paths:
				continue
			from_key = Path(from_meta.src).resolve().as_posix()

			out = [Path(to_meta.src).resolve().as_posix() for to_meta in tos]

			edges[from_key] = out
		return edges

	@staticmethod
	def _load_edges_into_global(edges: dict[str, list[str]]):
		builtins = GlobalContext.inference.get("builtins")
		for from_key, to_list in edges.items():
			from_meta = GlobalContext.path_index.get(Path(from_key).resolve())
			if not from_meta:
				continue
			out: list[ModuleMeta] = []
			if builtins:
				_add_unique(out, builtins)
			for to_key in to_list:
				to_meta = GlobalContext.path_index.get(Path(to_key).resolve())
				if to_meta:
					_add_unique(out, to_meta)
			GlobalContext.dependency_graph[from_meta] = out

	@staticmethod
	def _recompute_for_metas(
			lib, 
			metas: list[ModuleMeta], 
			progress: Optional[ProgressBar] = None, 
			log_files: bool = False
		):
		from ..utils.logging import logger
		builtins = GlobalContext.inference.get("builtins")
		total = len(metas)
		if total:
			logger.debug(f"{logger.emoji_map['patch']} [Cache] Recomputing {total} module(s)")
		for i, m in enumerate(metas, 1):
			GlobalContext.dependency_graph[m] = []
			if builtins:
				_add_unique(GlobalContext.dependency_graph[m], builtins)
			try:
				DependencyTracker(m).visit(m.tree)
			except (RecursionError, UnicodeError):
				continue
			if log_files:
				rel = Path(m.src).resolve().relative_to(lib.src.resolve())
				logger.debug(f"\t➜ {logger.emoji_map['file']} Recomputed {rel.as_posix()}")
			if progress is not None:
				progress.update(progress.iteration + 1)

	@staticmethod
	def build_graph_all(use_cache: bool = True):
		from ..utils.caching import GlobalCache
		from ..utils.logging import logger

		logger.debug(f"{logger.emoji_map['build']} [Cache] Starting dependency graph build")

		GlobalContext.meta_map.clear()
		GlobalContext.sysmodules.clear()
		GlobalContext.dependency_graph.clear()

		GraphBuilder.initialize_globals()

		plan: list[tuple[str, object, list[ModuleMeta], int]] = []
		total_modules = 0

		for lib in GlobalContext.libs.values():
			dep_file = GraphBuilder._dep_cache_file_for(lib)
			modified = GlobalCache.modified_map.get(lib.src, set())
			lib_count = len(lib.meta_map)
			total_modules += lib_count

			if use_cache and dep_file and dep_file.exists() and not modified:
				plan.append(("load", lib, [], lib_count))
				continue

			if use_cache and dep_file and dep_file.exists() and modified:
				metas = []
				for abs_posix in modified:
					meta = GlobalContext.path_index.get(Path(abs_posix).resolve())
					if meta:
						metas.append(meta)
				plan.append(("patch", lib, metas, lib_count))
				continue

			metas = list(lib.meta_map.values())
			plan.append(("full", lib, metas, lib_count))

		progress = ProgressBar(total_modules, prefix="Building dependency graph:")
		progress.display()

		for action, lib, metas, lib_count in plan:
			dep_file = GraphBuilder._dep_cache_file_for(lib)
			lib_name = lib.src.resolve().as_posix()

			if action == "load":
				if dep_file and dep_file.exists():
					data = json.loads(dep_file.read_text(encoding="utf-8"))
					edges = data.get("edges", {})
					GraphBuilder._load_edges_into_global(edges)
				progress.update(progress.iteration + lib_count)
				logger.debug(f"{logger.emoji_map['ok']} [Cache] Loaded {lib_count} module(s) from cache for {lib_name}")
				continue

			if action == "patch":
				if dep_file and dep_file.exists():
					data = json.loads(dep_file.read_text(encoding="utf-8"))
					edges = data.get("edges", {})
					GraphBuilder._load_edges_into_global(edges)

				cached_count = lib_count - len(metas)
				if cached_count > 0:
					progress.update(progress.iteration + cached_count)
					logger.debug(f"{logger.emoji_map['changed']} [Cache] {cached_count} module(s) reused from cache in {lib_name}")

				GraphBuilder._recompute_for_metas(lib, metas, progress=progress, log_files=True)

				if dep_file and not GlobalCache.is_blocked(lib.src):
					new_edges = GraphBuilder._serialize_edges_for(lib)
					dep_file.write_text(json.dumps({
						"library_src": lib.src.resolve().as_posix(),
						"edges": new_edges
					}, indent="\t"), encoding="utf-8")

				logger.debug(f"{logger.emoji_map['patch']} [Cache] Patched {len(metas)} module(s) in {lib_name}")
				continue

			if action == "full":
				GraphBuilder._recompute_for_metas(lib, metas, progress=progress, log_files=False)

				if dep_file and not GlobalCache.is_blocked(lib.src):
					new_edges = GraphBuilder._serialize_edges_for(lib)
					dep_file.write_text(json.dumps({
						"library_src": lib.src.resolve().as_posix(),
						"edges": new_edges
					}, indent="\t"), encoding="utf-8")

				logger.debug(f"{logger.emoji_map['libs']} [Cache] Fully rebuilt {lib_count} module(s) in {lib_name}")

		logger.debug(f"{logger.emoji_map['summary']} [Cache] Dependency graph build complete, sequences regenerated")

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
			if isinstance(table, Package): result.append(table.modules["__init__"])
			else: result.append(table)
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
		if self.in_function: return
		for alias in node.names: self.resolve_fqn_chain(alias.name)
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