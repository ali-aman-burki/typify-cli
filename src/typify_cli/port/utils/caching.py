from typing import Union, Optional
import ast
import pickle
import json
import hashlib
import os
import sys
import shutil
import io

from pathlib import Path
from dataclasses import dataclass

from .logging import logger
from .utils import Utils
from .progbar import ProgressBar, IndeterminateProgressBar
from ..preprocessing.library_meta import LibraryMeta
from ..preprocessing.module_meta import ModuleMeta
from ..preprocessing.instance_utils import Instance
from ..preprocessing.symbol_table import (
	Module,
	ClassDefinition,
	FunctionDefinition,
	CallFrame
)

@dataclass
class ModuleCache:
	tree: ast.Module
	trust_annotations: bool
	last_modified: float

	def to_meta(self, mpath: Path):
		return ModuleMeta(
			mpath,
			self.tree,
			self.trust_annotations,
			self.last_modified
		)

@dataclass
class LibStruct:
	path: Path
	mods: dict[Path, Path]
	index: dict[str, str]

@dataclass
class LibraryCache:
	lib_dir: Path
	lib_pickle: Path
	digest: str
	meta: LibraryMeta
	snapshot: dict[str, float] 

@dataclass
class InferenceCache:
	inference: dict[str, ModuleMeta]
	libs: dict[Path, LibraryMeta]
	sysmodules: dict[str, ModuleMeta]
	symbol_map: dict[Union[Union[Module, ClassDefinition], FunctionDefinition], Union[Instance, CallFrame]]
	function_object_map: dict[FunctionDefinition, Instance]
	singletons: dict[str, Instance]
	sequence_followed: list[str]
	last_progress: int

class GlobalCache:

	lib_structs: dict[Path, LibStruct] = {}
	libs_cache: dict[Path, LibraryCache] = {}
	global_index: dict[str, str] = {}
	context_index: dict[str, str] = {}
	modified_map: dict[Path, set[str]] = {}
	rebuilt_libs: set[Path] = set()
	staged_contexts: list[tuple[str, float, bytes]] = []
	blocked_libs: set[Path] = set()

	@staticmethod
	def is_blocked(lpath: Path) -> bool:
		return lpath in GlobalCache.blocked_libs
	
	@staticmethod
	def get_system_cache() -> Path:
		if sys.platform.startswith("win"):
			base = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
		elif sys.platform == "darwin":
			base = Path.home() / "Library" / "Caches"
		else:
			base = Path(os.getenv("XDG_CACHE_HOME", Path.home() / ".cache"))

		target_path = base / "typify"
		return target_path

	@staticmethod
	def stage_inference_context(
		libs: dict[Path, LibraryMeta], 
		processed_sequences: list[list[ModuleMeta]],
		sequence_followed: list[str],
		last_progress: int
	):
		if not GlobalCache.blocked_libs.isdisjoint(libs.keys()): return

		from ..preprocessing.core import GlobalContext

		context_id = repr(processed_sequences)
		last_modified = max(m.last_modified for seq in processed_sequences for m in seq)

		inference_cache = InferenceCache(
			inference=GlobalContext.inference,
			libs=libs,
			sysmodules=GlobalContext.sysmodules,
			symbol_map=GlobalContext.symbol_map,
			function_object_map=GlobalContext.function_object_map,
			singletons=GlobalContext.singletons,
			sequence_followed=sequence_followed,
			last_progress=last_progress
		)
		buf = io.BytesIO()
		
		try:
			pickle.dump(inference_cache, buf)
			GlobalCache.staged_contexts.append((context_id, last_modified, buf.getvalue()))
		except Exception as e:
			logger.debug(f"{logger.emoji_map['warn']} [Cache] Failed to stage inference context: {e}")
	@staticmethod
	def flush_inference_contexts(cache_path: Path):
		if not GlobalCache.staged_contexts:
			return

		context_dir = cache_path / "contexts"
		context_dir.mkdir(parents=True, exist_ok=True)

		staged_unique: dict[str, tuple[float, bytes]] = {}
		for cid, lm, data in GlobalCache.staged_contexts:
			staged_unique[cid] = (lm, data)

		progress = ProgressBar(
			total=len(staged_unique),
			prefix="Flushing Inference Contexts",
			progress_format="percent"
		)
		progress.display()

		for cid, (lm, data) in staged_unique.items():
			entry = GlobalCache.context_index.get(cid)
			if entry:
				context_file = Path(entry["path"])
			else:
				context_file = context_dir / f"{GlobalCache.context_counter}.pkl"
				GlobalCache.context_index[cid] = {
					"path": context_file.resolve().as_posix(),
					"last_modified": lm,
				}
				GlobalCache.context_counter += 1

			with open(context_file, "wb") as f:
				f.write(data)

			GlobalCache.context_index[cid]["last_modified"] = lm

			progress.update()

		index_file = context_dir / "index.json"
		payload = {"__counter__": GlobalCache.context_counter, **GlobalCache.context_index}
		with open(index_file, "w", encoding="utf-8") as f:
			json.dump(payload, f, indent="\t")

		GlobalCache.staged_contexts.clear()

	@staticmethod
	def load_inference_context(current_path: list[list[ModuleMeta]]) -> list[ModuleMeta]:
		from ..preprocessing.core import GlobalContext

		context_id = repr(current_path)
		entry = GlobalCache.context_index.get(context_id)
		if not entry:
			return []

		context_file = Path(entry["path"])
		if not context_file.exists():
			return []

		current_max = max(m.last_modified for seq in current_path for m in seq)
		saved_lm = entry["last_modified"]

		if current_max > saved_lm:
			return []

		with open(context_file, "rb") as f:
			context_cache: InferenceCache = pickle.load(f)
			meta_map: dict[Module, ModuleMeta] = {}

			remaining_libs = GlobalContext.libs.keys() - context_cache.libs.keys()
			for libpath in remaining_libs:
				meta_map.update(GlobalContext.libs[libpath].meta_map)

			for libpath, modified_files in GlobalCache.modified_map.items():
				if libpath not in context_cache.libs:
					continue
				if modified_files:
					logger.debug(
						f"{logger.emoji_map['patch']} [Cache] Patching {len(modified_files)} module(s) in {libpath.resolve()}"
					)
				for abs_posix in sorted(modified_files):
					abspath = Path(abs_posix)
					existing = GlobalContext.libs[libpath].get_meta_by_path(abspath)
					cached = context_cache.libs[libpath].get_meta_by_path(abspath)
					if existing is None or cached is None:
						continue
					cached.tree = existing.tree
					cached.trust_annotations = existing.trust_annotations
					existing.last_modified = cached.last_modified 
					relpath = abspath.relative_to(libpath)
					logger.debug(f"\t➜ {logger.emoji_map['file']} Patched {relpath}")

			for c_libpath in context_cache.libs:
				GlobalContext.libs[c_libpath] = context_cache.libs[c_libpath]
				meta_map.update(context_cache.libs[c_libpath].meta_map)

			GlobalContext.meta_map = meta_map
			GlobalContext.inference = context_cache.inference
			GlobalContext.sysmodules = context_cache.sysmodules
			GlobalContext.symbol_map = context_cache.symbol_map
			GlobalContext.function_object_map = context_cache.function_object_map
			GlobalContext.singletons = context_cache.singletons
			GlobalContext.path_index = {m.src: m for m in GlobalContext.meta_map.values()}
			GlobalContext.progress_bar.iteration = context_cache.last_progress

			return context_cache.sequence_followed

		return []

	@staticmethod
	def compute_snapshot(lpath: Path) -> dict[str, float]:
		return {
			p.relative_to(lpath).as_posix(): p.stat().st_mtime
			for p in lpath.rglob("*")
			if p.suffix in {".py", ".pyi"}
		}

	@staticmethod
	def setup(
		cache_path: Path,
		clear_cache: bool,
		config_paths: list[Path]
	) -> list[LibraryMeta]:
		
		cache_path.mkdir(parents=True, exist_ok=True)

		if clear_cache:
			GlobalCache.clear(cache_path)

		libs: dict[Path, LibraryMeta] = {}

		global_index_file = cache_path / "index.json"
		if global_index_file.exists():
			with global_index_file.open("r", encoding="utf-8") as f:
				GlobalCache.global_index = json.load(f)
		else:
			GlobalCache.global_index = {}

		context_index_file = cache_path / "contexts" / "index.json"
		if context_index_file.exists():
			with context_index_file.open("r", encoding="utf-8") as f:
				raw_index: dict = json.load(f)
			GlobalCache.context_counter = int(raw_index.pop("__counter__", 0))
			GlobalCache.context_index = {
				cid: {"path": val["path"], "last_modified": float(val["last_modified"])}
				for cid, val in raw_index.items()
			}
		else:
			GlobalCache.context_index = {}
			GlobalCache.context_counter = 0

		for lpath in config_paths:
			lpath_str = str(lpath)
			blocked = GlobalCache.is_blocked(lpath)

			lib_id = GlobalCache.global_index.get(lpath_str)

			if lib_id is not None:
				lib_dir = cache_path / lib_id
				lib_pickle = lib_dir / "library.pkl" if lib_dir.exists() else None
			else:
				lib_dir = None
				lib_pickle = None

			has_existing_cache = bool(lib_pickle and lib_pickle.exists())

			if lib_id is None and not blocked:
				lib_id = str(len(GlobalCache.global_index))
				GlobalCache.global_index[lpath_str] = lib_id
				lib_dir = cache_path / lib_id
				lib_dir.mkdir(parents=True, exist_ok=True)
				lib_pickle = lib_dir / "library.pkl"

			snapshot = GlobalCache.compute_snapshot(lpath)
			digest = hashlib.sha1(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()

			progress_bar = IndeterminateProgressBar(
				prefix=f"Locating modules in {Utils.last_n_parts(lpath, 2)}",
				suffix="Checking cache",
			)
			progress_bar.start()

			cached: Optional[LibraryCache] = None
			if lib_pickle and lib_pickle.exists():
				try:
					with open(lib_pickle, "rb") as f:
						cached = pickle.load(f)
					if cached.digest == digest:
						GlobalCache.libs_cache[lpath] = cached
						libs[cached.meta.src] = cached.meta
						module_count = len(cached.meta.meta_map)
						progress_bar.set_suffix(f"Cached: {module_count} modules")
						logger.debug(f"{logger.emoji_map['ok']} [Cache] {lpath.as_posix()}")
						logger.debug(f"\tReused {module_count} modules (cache hit)")
						GlobalCache.modified_map[lpath] = set()
						progress_bar.done()

						index_file = lib_dir / "index.json"
						if index_file.exists():
							with index_file.open("r", encoding="utf-8") as f:
								index = json.load(f)
							mods: dict[Path, Path] = {}
							for key, original in index.items():
								fpath = lib_dir / f"{key}.pkl"
								if fpath.exists():
									mods[Path(original)] = fpath
							GlobalCache.lib_structs[lpath] = LibStruct(lib_dir, mods, index)
						else:
							GlobalCache.lib_structs[lpath] = LibStruct(lib_dir, {}, {})
						continue
				except Exception as e:
					logger.debug(f"{logger.emoji_map['warn']} [Cache] {lpath.as_posix()}")
					logger.debug(f"\tCorrupted cache pickle, forcing rebuild ({e})")
					cached = None

			if lib_dir and (lib_dir / "index.json").exists():
				with (lib_dir / "index.json").open("r", encoding="utf-8") as f:
					index = json.load(f)
				mods: dict[Path, Path] = {}
				for key, original in index.items():
					fpath = lib_dir / f"{key}.pkl"
					if fpath.exists():
						mods[Path(original)] = fpath
				GlobalCache.lib_structs[lpath] = LibStruct(lib_dir, mods, index)
			else:
				if not blocked:
					GlobalCache.lib_structs[lpath] = LibStruct(lib_dir or Path(), {}, {})

			if cached is not None and isinstance(cached.meta, LibraryMeta):
				old_snapshot = cached.snapshot or {}
				old_paths = set(old_snapshot.keys())
				new_paths = set(snapshot.keys())

				added    = new_paths - old_paths
				removed  = old_paths - new_paths
				common   = new_paths & old_paths
				modified = {p for p in common if snapshot[p] != old_snapshot[p]}

				if not added and not removed:
					meta = cached.meta
					module_count = len(meta.meta_map)
					logger.debug(f"{logger.emoji_map['patch']} [Cache] {lpath.as_posix()}")
					logger.debug(f"\tIncremental refresh: {len(modified)} trees updated")
					logger.debug(f"\tTotal modules: {module_count}")

					abs_posix_modified = {(lpath / rel).resolve().as_posix() for rel in modified}
					GlobalCache.modified_map[lpath] = abs_posix_modified

					for rel in sorted(modified):
						abspath = (lpath / rel).resolve()
						existing = meta.get_meta_by_path(abspath)
						if existing is None:
							logger.debug(f"\t➜ {logger.emoji_map['warn']} Skipping {rel}, not found in meta")
							continue

						refreshed = GlobalCache.get_module_meta(
							lpath,
							abspath,
							existing.trust_annotations
						)
						existing.tree = refreshed.tree
						existing.trust_annotations = refreshed.trust_annotations
						existing.last_modified = refreshed.last_modified
						logger.debug(f"\t➜ {logger.emoji_map['file']} Updated tree for {rel}")

					libcache = LibraryCache(
						lib_dir=lib_dir,
						lib_pickle=lib_pickle,
						digest=digest,
						meta=meta,
						snapshot=snapshot,
					)
					if not blocked and lib_pickle:
						with open(lib_pickle, "wb") as f:
							pickle.dump(libcache, f)

					GlobalCache.libs_cache[lpath] = libcache
					libs[meta.src] = meta
					progress_bar.set_suffix(f"Cached: {module_count} modules")
					progress_bar.done()
					continue

			if blocked and not has_existing_cache:
				meta = LibraryMeta(lpath)
				meta.build(progress_bar=progress_bar)
				module_count = len(meta.meta_map)
				logger.debug(f"{logger.emoji_map['build']} [Cache] {lpath.as_posix()}")
				logger.debug(f"\tFull rebuild (blocked, not cached)")
				logger.debug(f"\tTotal modules: {module_count}")

				GlobalCache.rebuilt_libs.add(lpath)
				GlobalCache.modified_map[lpath] = set()

				libs[meta.src] = meta
				progress_bar.done()
				continue

			meta = LibraryMeta(lpath)
			meta.build(progress_bar=progress_bar)
			module_count = len(meta.meta_map)
			logger.debug(f"{logger.emoji_map['build']} [Cache] {lpath.as_posix()}")
			logger.debug(f"\tFull rebuild performed")
			logger.debug(f"\tTotal modules: {module_count}")

			GlobalCache.rebuilt_libs.add(lpath)
			GlobalCache.modified_map[lpath] = set()

			libcache = LibraryCache(
				lib_dir=lib_dir,
				lib_pickle=lib_pickle,
				digest=digest,
				meta=meta,
				snapshot=snapshot,
			)
			if not blocked and lib_pickle:
				with open(lib_pickle, "wb") as f:
					pickle.dump(libcache, f)

			GlobalCache.libs_cache[lpath] = libcache
			libs[meta.src] = meta
			progress_bar.done()

		with global_index_file.open("w", encoding="utf-8") as f:
			json.dump(GlobalCache.global_index, f, indent='\t')

		total_modules = sum(len(meta.meta_map) for meta in libs.values())
		logger.debug(f"{logger.emoji_map['ok']} [Cache Summary]")
		logger.debug(f"\tLibraries processed: {len(libs)}")
		logger.debug(f"\tTotal modules: {total_modules}")

		return libs

	@staticmethod
	def get_module_meta(lpath: Path, mpath: Path, trust_annotations: bool):
		libcache = GlobalCache.lib_structs.get(lpath)

		if libcache is None or not libcache.path.exists():
			new_mcache = ModuleCache(
				Utils.load_tree(mpath),
				trust_annotations,
				mpath.stat().st_mtime
			)
			return new_mcache.to_meta(mpath)

		pickled = libcache.mods.get(mpath)
		if pickled and pickled.exists():
			with open(pickled, "rb") as f:
				mcache: ModuleCache = pickle.load(f)
				if mcache.last_modified == mpath.stat().st_mtime:
					return mcache.to_meta(mpath)

		new_mcache = ModuleCache(
			Utils.load_tree(mpath),
			trust_annotations,
			mpath.stat().st_mtime
		)

		if GlobalCache.is_blocked(lpath):
			return new_mcache.to_meta(mpath)

		if mpath in libcache.mods:
			fname = pickled.stem
		else:
			fname = str(len(libcache.index))
		pickled_path = libcache.path / f"{fname}.pkl"

		with open(pickled_path, "wb") as wf:
			pickle.dump(new_mcache, wf)

		libcache.mods[mpath] = pickled_path
		libcache.index[fname] = mpath.as_posix()

		index_file = libcache.path / "index.json"
		with index_file.open("w", encoding="utf-8") as f:
			json.dump(libcache.index, f, indent='\t')

		return new_mcache.to_meta(mpath)

	@staticmethod
	def prune():
		from hashlib import sha1

		def compute_digest(lpath: Path) -> str:
			snapshot = {
				p.relative_to(lpath).as_posix(): p.stat().st_mtime
				for p in lpath.rglob("*")
				if p.suffix in {".py", ".pyi"}
			}
			return sha1(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()

		dead_libs: set[str] = set()

		# --- prune libraries ---
		for lpath, libcache in list(GlobalCache.libs_cache.items()):
			if not lpath.exists():
				if libcache.lib_pickle.exists():
					libcache.lib_pickle.unlink()
				GlobalCache.libs_cache.pop(lpath, None)
				dead_libs.add(lpath.as_posix())
				continue

			digest = compute_digest(lpath)
			if digest != libcache.digest:
				if libcache.lib_pickle.exists():
					libcache.lib_pickle.unlink()
				GlobalCache.libs_cache.pop(lpath, None)
				dead_libs.add(lpath.as_posix())

		for _, libstruct in GlobalCache.lib_structs.items():
			to_remove = []
			for key, mpath in libstruct.index.items():
				if not Path(mpath).exists():
					to_remove.append(key)
			for key in to_remove:
				libstruct.index.pop(key, None)
				fpath = libstruct.path / f"{key}.pkl"
				if fpath.exists():
					fpath.unlink()

			valid = set(libstruct.index.keys())
			for file in libstruct.path.glob("*.pkl"):
				if file.stem not in valid:
					file.unlink()

			mods: dict[Path, Path] = {}
			for key, original in libstruct.index.items():
				fpath = libstruct.path / f"{key}.pkl"
				if fpath.exists():
					mods[Path(original)] = fpath
			libstruct.mods = mods

			index_file = libstruct.path / "index.json"
			with index_file.open("w", encoding="utf-8") as f:
				json.dump(libstruct.index, f, indent='\t')

		if dead_libs:
			to_delete = [path for path in GlobalCache.global_index if path in dead_libs]
			for path in to_delete:
				GlobalCache.global_index.pop(path, None)

			global_index_file = GlobalCache.get_system_cache() / "index.json"
			if global_index_file.exists():
				with global_index_file.open("w", encoding="utf-8") as f:
					json.dump(GlobalCache.global_index, f, indent='\t')

		context_dir = GlobalCache.get_system_cache() / "contexts"
		if context_dir.exists():
			to_remove = []
			for cid, path_str in list(GlobalCache.context_index.items()):
				path = Path(path_str)
				if not path.exists():
					to_remove.append(cid)
					continue
				try:
					with open(path, "rb") as f:
						pickle.load(f)  # sanity check
				except Exception:
					to_remove.append(cid)
					if path.exists():
						path.unlink()

			for cid in to_remove:
				GlobalCache.context_index.pop(cid, None)

			valid_paths = {Path(p) for p in GlobalCache.context_index.values()}
			for file in context_dir.glob("*.pkl"):
				if file not in valid_paths:
					file.unlink()

			index_file = context_dir / "index.json"
			with index_file.open("w", encoding="utf-8") as f:
				json.dump(GlobalCache.context_index, f, indent="\t")


	@staticmethod
	def clear(cache_path: Path):
		if cache_path.exists():
			shutil.rmtree(cache_path, ignore_errors=True)

		GlobalCache.lib_structs.clear()
		GlobalCache.libs_cache.clear()
		GlobalCache.global_index.clear()
		GlobalCache.context_index.clear()
		GlobalCache.modified_map.clear()
		GlobalCache.rebuilt_libs.clear()