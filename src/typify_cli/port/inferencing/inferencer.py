import time
import json

from pathlib import Path

_merge_dir = str(Path(__file__).parent.parent)
from ..utils.logging import logger
from ..utils.progbar import ProgressBar
from ..utils.utils import Utils
from ..utils.caching import GlobalCache
from ..preprocessing.module_meta import ModuleMeta
from ..preprocessing.library_meta import LibraryMeta
from .commons import Builtins
from .typeutils import TypeUtils
from .executor import Executor
from ..preprocessing.core import GlobalContext
from ..preprocessing.sequencer import Sequencer

class Inferencer:

	@staticmethod
	def _run_pass(meta: ModuleMeta, sequence_followed: list[str]) -> tuple[dict, dict]:
		GlobalContext.sysmodules.setdefault(
			meta.table.fqn,
			TypeUtils.instantiate_with_args(Builtins.get_type("module"))
		)
		GlobalContext.symbol_map[meta.table] = GlobalContext.sysmodules[meta.table.fqn]

		logger.debug(f"{logger.emoji_map['types']} Inferring for {meta.table.fqn}")

		executor = Executor(
			module_meta=meta,
			symbol=meta.table,
			namespace=GlobalContext.sysmodules[meta.table.fqn],
			caller=None,
			arguments={},
			tree=meta.tree,
		)
		executor.execute()
		sequence_followed.append(meta.table.fqn)
		GlobalContext.sysmodules[meta.table.fqn].update_type_info(Builtins.get_type("module"))
		return meta.snapshot()

	@staticmethod
	def _run_passes(
		sequence: list[ModuleMeta], 
		sequence_followed: list[str]
	) -> list[tuple[dict, dict]]:
		return [Inferencer._run_pass(meta, sequence_followed) for meta in sequence]

	@staticmethod
	def process_sequence(
		sequence: list[ModuleMeta],
		sequence_followed: list[str]
	) -> None:

		has_self_loop = len(sequence) == 1 and sequence[0] in GlobalContext.dependency_graph.get(sequence[0], [])
		needs_fixpoint = has_self_loop or len(sequence) > 1

		if needs_fixpoint:
			prev_snapshots = []
			while True:
				curr_snapshots = Inferencer._run_passes(
					sequence, 
					sequence_followed
				)
				if curr_snapshots == prev_snapshots:
					break
				prev_snapshots = curr_snapshots
		else:
			Inferencer._run_pass(sequence[0], sequence_followed)

	@staticmethod
	def _init_structures():
		corrected_sequences: list[list[ModuleMeta]] = []
		captured_metas: set[ModuleMeta] = set()

		sequences = Sequencer.generate_sequences(GlobalContext.dependency_graph)
		project_only_modules: set[ModuleMeta] = set(next(iter(GlobalContext.libs.values())).meta_map.values())

		for sequence in sequences:
			if captured_metas == project_only_modules:
				break
			for meta in sequence:
				if meta in project_only_modules:
					captured_metas.add(meta)
			corrected_sequences.append(sequence)

		return corrected_sequences

	@staticmethod
	def preinfer(heur_driven: bool, topn: int):
		corrected_sequences = Inferencer._init_structures()
		project_lib = next(iter(GlobalContext.libs.values()))
		project_only_modules: set[ModuleMeta] = set(project_lib.meta_map.values())

		flattened = [meta for sequence in corrected_sequences for meta in sequence]
		total_modules = len(flattened)
		
		progress = ProgressBar(total=total_modules, prefix="Preprocessing:")
		progress.display()

		total_counts = 0

		typemap_path = Path(f"{_merge_dir}/typemap.json")
		if typemap_path.is_file():
			with open(typemap_path, "r", encoding="utf-8") as f:
				typemap = json.load(f)

		for i in range(total_modules):
			meta = flattened[i]
			total_counts += meta.precollect(
				typeslots=meta in project_only_modules, 
				infer=heur_driven,
				topn=topn,
				typemap=typemap
			)
			progress.update()

		inferred_types = project_lib.get_types_per_file(
			topn=topn
		)

		logger.debug(f"{logger.emoji_map['ok']} [Inferencer] Preprocessed {total_modules} module(s)", trail=1)
		
		return total_counts, project_lib, corrected_sequences, inferred_types

	@staticmethod
	def infer(
		total_counts: int,
		project_lib: LibraryMeta,
		corrected_sequences: list[list[ModuleMeta]],
		topn: int
	):
		start_time = time.time()

		GlobalContext.progress_bar = ProgressBar(
			total=total_counts,
			prefix="Performing Inference",
			progress_format="percent"
		)
		GlobalContext.progress_bar.display()
		
		logger.debug("", header=False)
		logger.debug(f"{logger.emoji_map['search']} {len(corrected_sequences)} total sequences to process")
		logger.debug("", header=False)
		
		pretty = Utils.pretty_list_arrow(corrected_sequences, columns=3)
		logger.debug(pretty, header=False)
		
		rebuilt_libs = GlobalCache.rebuilt_libs
		filter_1: list[list[ModuleMeta]] = []
		
		for i in range(len(corrected_sequences), 0, -1):
			current_path = corrected_sequences[:i]
			flat = {mod for sublist in current_path for mod in sublist}
			matching_libs = {
				k
				for k, lib in GlobalContext.libs.items()
				if flat.intersection(lib.meta_map.values())
			}
			contains_rebuilt = matching_libs.intersection(rebuilt_libs)
			if not contains_rebuilt:
				modified = False
				for ml in matching_libs:
					search_space = GlobalCache.modified_map.get(ml, set())
					if any(f.src.resolve().as_posix() in search_space for f in flat):
						modified = True
						break
				if not modified:
					filter_1 = current_path
					break
		
		remaining = corrected_sequences.copy()
		processed_sequences: list[list[ModuleMeta]] = []
		sequence_followed: list[str] = []

		logger.debug(f"{logger.emoji_map['search']} Checking cache for contexts.")
		for i in range(len(filter_1), 0, -1):
			current_path = filter_1[:i]
			sequence_followed = GlobalCache.load_inference_context(current_path)
			if sequence_followed:
				logger.debug(f"{logger.emoji_map['ok']} [Cache] Cache hit for {i} sequences (restored {len(set(sequence_followed))} module(s))")
				new_graph = {}
				for meta, deps in GlobalContext.dependency_graph.items():
					new_meta = GlobalContext.path_index.get(meta.src, meta)
					new_deps = [GlobalContext.path_index.get(d.src, d) for d in deps]
					new_graph[new_meta] = new_deps
				GlobalContext.dependency_graph = new_graph

				corrected_sequences = Inferencer._init_structures()
				remaining = corrected_sequences[i:]
				processed_sequences = corrected_sequences[:i]
				GlobalContext.progress_bar.update(GlobalContext.progress_bar.iteration)
				break
		
		if not remaining:
			logger.debug(f"{logger.emoji_map['ok']} [Cache] Full cached context restored. Inference Skipped.")
		elif remaining and sequence_followed:
			logger.debug(f"{logger.emoji_map['ok']} [Cache] Partial cached context restored. Remaining Inference Started.")
		elif not sequence_followed: 
			logger.debug(f"{logger.emoji_map['refresh']} [Cache] No cached context found. Recomputing Inference.")

		logger.debug("", header=False)

		for sequence in remaining:
			Inferencer.process_sequence(
				sequence,
				sequence_followed
			)
			processed_sequences.append(sequence)

			current_path = processed_sequences
			flat = {mod for sublist in current_path for mod in sublist}

			libs = {
				k: lib
				for k, lib in GlobalContext.libs.items()
				if flat.intersection(lib.meta_map.values())
			}
			
			GlobalCache.stage_inference_context(
				libs,
				processed_sequences,
				sequence_followed,
				GlobalContext.progress_bar.iteration
			)
		
		if GlobalContext.progress_bar.iteration < GlobalContext.progress_bar.total:
			print()
		end_time = time.time()
		if remaining: logger.debug("", header=False)

		logger.debug("Sequence Followed:")
		
		pretty = Utils.pretty_list_arrow(sequence_followed, columns=3)
		logger.debug(pretty, header=False)

		logger.info(f"{logger.emoji_map['ok']} Inference complete:")
		logger.info(f"\t\tSequences processed: {len(processed_sequences)}")
		logger.info(f"\t\tTotal Modules: {len(set(sequence_followed))}")
		logger.info(f"\t\tTime Taken: {end_time - start_time:.4f} seconds")
		if GlobalContext.progress_bar.total > 0:
			percent = (
				GlobalContext.progress_bar.iteration
				/ GlobalContext.progress_bar.total
			) * 100
		else:
			percent = 100.0

		logger.info(f"\t\tProgress: {percent:.2f} percent")

		inferred_types = project_lib.get_types_per_file(
			topn=topn
		)
		return inferred_types