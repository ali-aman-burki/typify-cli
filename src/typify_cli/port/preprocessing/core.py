from pathlib import Path
from typing import Union

from ..utils.progbar import ProgressBar
from .library_meta import LibraryMeta
from .module_meta import ModuleMeta
from .instance_utils import Instance
from ..inferencing.call_stack import CallStack
from .symbol_table import (
	Module,
	ClassDefinition,
	FunctionDefinition,
	CallFrame
)

class GlobalContext:
	libs: dict[Path, LibraryMeta] = {}
	call_stack: CallStack = CallStack()
	inference: dict[str, ModuleMeta] = {}
	sysmodules: dict[str, Instance] = {}
	symbol_map: dict[Union[Union[Module, ClassDefinition], FunctionDefinition], Union[Instance, CallFrame]] = {}
	function_object_map: dict[FunctionDefinition, Instance] = {}
	meta_map: dict[Module, ModuleMeta] = {}
	dependency_graph: dict[ModuleMeta, list[ModuleMeta]] = {}
	progress_bar: ProgressBar = None

	path_index: dict[Path, ModuleMeta] = {}
	singletons: dict[str, Instance] = {"True": None, "False": None, "None": None}