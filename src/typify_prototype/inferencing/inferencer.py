from typify_prototype.preprocessing.module_meta import ModuleMeta
from typify_prototype.preprocessing.library_meta import LibraryMeta
from typify_prototype.inferencing.commons import Builtins
from typify_prototype.inferencing.typeutils import TypeUtils
from typify_prototype.inferencing.executor import Executor
from typify_prototype.preprocessing.core import GlobalContext
from typify_prototype.preprocessing.sequencer import Sequencer


class Inferencer:

    @staticmethod
    def _run_pass(meta: ModuleMeta, sequence_followed: list[str]) -> tuple[dict, dict]:
        GlobalContext.sysmodules.setdefault(
            meta.table.fqn,
            TypeUtils.instantiate_with_args(Builtins.get_type("module"))
        )
        GlobalContext.symbol_map[meta.table] = GlobalContext.sysmodules[meta.table.fqn]

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
                curr_snapshots = Inferencer._run_passes(sequence, sequence_followed)
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
    def preinfer():
        corrected_sequences = Inferencer._init_structures()
        project_lib = next(iter(GlobalContext.libs.values()))
        project_only_modules: set[ModuleMeta] = set(project_lib.meta_map.values())

        flattened = [meta for sequence in corrected_sequences for meta in sequence]

        for meta in flattened:
            meta.precollect(typeslots=meta in project_only_modules)

        return project_lib, corrected_sequences

    @staticmethod
    def infer(
        project_lib: LibraryMeta,
        corrected_sequences: list[list[ModuleMeta]],
    ):
        sequence_followed: list[str] = []

        for sequence in corrected_sequences:
            Inferencer.process_sequence(sequence, sequence_followed)

        return project_lib.get_types_per_file()
