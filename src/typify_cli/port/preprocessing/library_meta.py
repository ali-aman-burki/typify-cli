import json

from pathlib import Path
from collections import (
	defaultdict,
	OrderedDict
)

from .symbol_table import (
	Library,
	Package,
	Module,
)
from .instance_utils import Instance
from .module_meta import ModuleMeta
from ..utils.progbar import (
	ProgressBar,
	IndeterminateProgressBar
)

class LibraryMeta:
	def __init__(self, src: Path):
		self.src = Path(src).resolve()
		self.library_table = Library(self.src.name)
		self.sysmodules: dict[str, Instance] = {}
		self.meta_map: dict[Module, ModuleMeta] = {}
		self.dependency_graph: dict[ModuleMeta, list[ModuleMeta]] = {}
		self.fqn_map: dict[str, list[Package, Module]] = {}
		self.path_index: dict[Path, ModuleMeta] = {}

	def build(self, progress_bar: IndeterminateProgressBar):
		from ..utils.caching import GlobalCache
		
		working_is_package = (self.src / "__init__.py").is_file() or (self.src / "__init__.pyi").is_file()

		if working_is_package:
			root_package_table = Package(self.src.name)
			root_package_table.trust_annotations = False
			self.library_table.set_package(root_package_table, self.fqn_map)
			package_map = {self.src: root_package_table}
		else:
			self.library_table.trust_annotations = False
			package_map = {self.src: self.library_table}

		def has_valid_package_chain(path: Path, src: Path) -> bool:
			while path != src:
				if not ((path / "__init__.py").is_file() or (path / "__init__.pyi").is_file()):
					return False
				path = path.parent
			return True

		for path in sorted(self.src.rglob("*")):
			if path.is_dir():
				if "__pycache__" in path.parts:
					continue

				has_init = (path / "__init__.py").is_file() or (path / "__init__.pyi").is_file()
				if has_init and has_valid_package_chain(path, self.src):
					parent_table = package_map.get(path.parent, self.library_table)
					package_table = Package(path.name)
					package_table.trust_annotations = parent_table.trust_annotations
					package_map[path] = package_table
					parent_table.set_package(package_table, self.fqn_map)

			elif path.name == "py.typed":
				parent = path.parent
				table = package_map.get(parent)
				if table:
					table.trust_annotations = True

		for dir_path, package_table in package_map.items():
			for ext in [".pyi", ".py"]:
				init_path = dir_path / f"__init__{ext}"
				if init_path.is_file():
					init_path = init_path.resolve()
					meta = GlobalCache.get_module_meta(
						self.src, 
						init_path, 
						package_table.trust_annotations
					)
					package_table.set_module(meta.table, self.fqn_map)
					self.meta_map[meta.table] = meta
					self.path_index[Path(meta.src).resolve()] = meta
					progress_bar.set_suffix(f"Parsed: {len(self.meta_map)} modules")
					break

		module_candidates = defaultdict(dict)
		for path in sorted(self.src.rglob("*")):
			if path.suffix in {".py", ".pyi"} and not path.name.startswith("__init__.py"):
				parent = path.parent
				if parent in package_map:
					stem = path.stem
					module_candidates[(parent, stem)][path.suffix] = path

		for (parent, stem), variants in module_candidates.items():
			chosen_path = variants.get(".pyi") or variants.get(".py")
			if not chosen_path:
				continue

			table = package_map[parent]
			chosen_path: Path = chosen_path.resolve()
			meta = GlobalCache.get_module_meta(
				self.src,
				chosen_path,
				True if chosen_path.suffix == ".pyi" else table.trust_annotations
			)
			table.set_module(meta.table, self.fqn_map)
			self.meta_map[meta.table] = meta
			self.path_index[Path(meta.src).resolve()] = meta
			progress_bar.set_suffix(f"Parsed: {len(self.meta_map)} modules")
		
		progress_bar.set_suffix(f"Parsed: {len(self.meta_map)} modules")
		progress_bar.done()

	def get_meta_by_path(self, mpath: Path):
		return self.path_index.get(Path(mpath).resolve())

	def export_symbols(self, output: Path):
		progress = ProgressBar(
			len(self.meta_map) + 1, 
			prefix="Exporting Symbols",
			progress_format="percent"
		)
		progress.display()
		
		data = {}
		for i, meta in enumerate(self.meta_map.values(), 1):
			data[str(meta.src.as_posix())] = meta.table.to_dict()
			progress.update(i)
		
		sorted_data = OrderedDict()
		sorted_data["project_path"] = str(self.src.as_posix())
		for k in sorted(data):
			sorted_data[k] = data[k]
		
		with output.open("w", encoding="utf-8") as f:
			json.dump(sorted_data, f, indent='\t', ensure_ascii=False)
		
		progress.update(len(self.meta_map) + 1)

	def get_types_per_file(self, topn: int):
		progress = ProgressBar(
			len(self.meta_map) + 1,
			prefix="Exporting Types",
			progress_format="percent"
		)
		progress.display()

		data = {}
		for i, meta in enumerate(self.meta_map.values(), 1):
			src_rel_path = meta.src.as_posix()
			result = meta.typeslots(topn=topn, merge_buckets=True)
			if result:
				data[src_rel_path] = result

			progress.update(i)

		progress.update(len(self.meta_map) + 1)
		return data