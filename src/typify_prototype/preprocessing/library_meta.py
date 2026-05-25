from pathlib import Path
from collections import defaultdict, OrderedDict

from typify_prototype.preprocessing.symbol_table import Library, Package, Module
from typify_prototype.preprocessing.instance_utils import Instance
from typify_prototype.preprocessing.module_meta import ModuleMeta


class LibraryMeta:
    def __init__(self, src: Path):
        self.src = Path(src).resolve()
        self.library_table = Library(self.src.name)
        self.sysmodules: dict[str, Instance] = {}
        self.meta_map: dict[Module, ModuleMeta] = {}
        self.dependency_graph: dict[ModuleMeta, list[ModuleMeta]] = {}
        self.fqn_map: dict[str, list] = {}
        self.path_index: dict[Path, ModuleMeta] = {}

    def build(self):
        from typify_prototype.utils.utils import Utils

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
                table = package_map.get(path.parent)
                if table:
                    table.trust_annotations = True

        for dir_path, package_table in package_map.items():
            for ext in [".pyi", ".py"]:
                init_path = dir_path / f"__init__{ext}"
                if init_path.is_file():
                    init_path = init_path.resolve()
                    tree = Utils.load_tree(init_path)
                    meta = ModuleMeta(init_path, tree, package_table.trust_annotations, init_path.stat().st_mtime)
                    package_table.set_module(meta.table, self.fqn_map)
                    self.meta_map[meta.table] = meta
                    self.path_index[Path(meta.src).resolve()] = meta
                    break

        module_candidates = defaultdict(dict)
        for path in sorted(self.src.rglob("*")):
            if path.suffix in {".py", ".pyi"} and not path.name.startswith("__init__"):
                parent = path.parent
                if parent in package_map:
                    module_candidates[(parent, path.stem)][path.suffix] = path

        for (parent, stem), variants in module_candidates.items():
            chosen_path = variants.get(".pyi") or variants.get(".py")
            if not chosen_path:
                continue
            table = package_map[parent]
            chosen_path = chosen_path.resolve()
            trust = True if chosen_path.suffix == ".pyi" else table.trust_annotations
            tree = Utils.load_tree(chosen_path)
            meta = ModuleMeta(chosen_path, tree, trust, chosen_path.stat().st_mtime)
            table.set_module(meta.table, self.fqn_map)
            self.meta_map[meta.table] = meta
            self.path_index[Path(meta.src).resolve()] = meta

    def get_meta_by_path(self, mpath: Path):
        return self.path_index.get(Path(mpath).resolve())

    def get_types_per_file(self):
        data = {}
        for meta in self.meta_map.values():
            result = meta.typeslots(merge_buckets=True)
            if result:
                data[meta.src.as_posix()] = result
        return data
