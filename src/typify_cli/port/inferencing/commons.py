import ast

from typing import Union, Optional
from dataclasses import dataclass

from ..preprocessing.instance_utils import (
	Instance,
	ReferenceSet
) 
from ..preprocessing.symbol_table import (
    ClassDefinition, 
    Module,
)

@dataclass
class ResolvedArg:
    values: object
    refset: ReferenceSet

@dataclass(eq=False)
class ParameterEntry:
	name: str
	refset: ReferenceSet
	defkey: tuple[Module, tuple[int, int]]

	is_vararg: bool = False
	is_kwarg: bool = False
	is_kwonly: bool = False
	is_posonly: bool = False
	
	node: ast.expr = None
	annotation: Instance = None

@dataclass
class ArgTuple:
	refset: ReferenceSet
	defkey: tuple[Module, tuple[int, int]]

class Singletons:

	_typenames = {
		"True": "bool",
		"False": "bool",
		"None": "NoneType",
	}

	singname_to_cval = {
		"True": True,
		"False": False,
		"None": None,
	}

	@staticmethod
	def get(singname: str):
		from ..preprocessing.core import GlobalContext
		from ..inferencing.typeutils import TypeUtils

		if singname not in GlobalContext.singletons: return None

		entry = GlobalContext.singletons.get(singname)
		typename = Singletons._typenames.get(singname)
		btype = Builtins.get_type(typename)

		if isinstance(entry, Instance):
			entry.update_type_info(btype)
			return entry
		else:
			instance = TypeUtils.instantiate_with_args(btype)
			instance.cval = Singletons.singname_to_cval[singname]
			GlobalContext.singletons[singname] = instance
			return instance

class Checker:
	@staticmethod
	def match_origin(lhs: ClassDefinition, rhs: ClassDefinition):
		return lhs and lhs == rhs
	
	@staticmethod
	def is_subclass(c1: ClassDefinition, c2: Union[ClassDefinition, tuple[ClassDefinition, ...]]):
		if isinstance(c2, tuple):
			return any(c1 and c2 and c1.mro[0] in cls.mro for cls in c2)
		return c1 and c2 and c1.mro[0] in c2.mro

	@staticmethod
	def is_alias(instance: Instance):
		return instance.instanceof(
			Types.get_type("UnionType"),
			Types.get_type("GenericAlias"),
			Typing.get_type("_GenericAlias"),
			Typing.get_type("_UnpackGenericAlias"),
			Typing.get_type("_UnionGenericAlias")
		)
	
	@staticmethod
	def is_unionable(instance: Instance):
		return (
			Checker.is_type(instance) or
			Checker.is_alias(instance) or
			Checker.is_typevar(instance)
		) 
	
	@staticmethod
	def is_type(instance: Instance):
		return instance.instanceof(
			Builtins.get_type("type")
		)

	@staticmethod
	def is_typevar(instance: Instance):
		return instance.instanceof(
			Typing.get_type("TypeVar")
		)
	
	@staticmethod
	def is_typevartuple(instance: Instance):
		return instance.instanceof(
			Typing.get_type("TypeVarTuple")
		)

class Builtins:

	@staticmethod
	def module() -> Module:
		from ..preprocessing.core import GlobalContext
		try:
			result = GlobalContext.inference["builtins"].table
			return result
		except Exception:
			return None
	
	@staticmethod
	def get_type(type_name: str) -> Optional[ClassDefinition]:
		try: 
			result = Builtins.module().classes[type_name].get_latest_definition()
			return result
		except Exception: 
			return None

class Typing:
	
	@staticmethod
	def module() -> Module:
		from ..preprocessing.core import GlobalContext
		try:
			result = GlobalContext.inference["typing"].table
			return result
		except Exception:
			return None
	
	@staticmethod
	def get_type(type_name: str) -> Optional[ClassDefinition]:
		try: 
			result = Typing.module().classes[type_name].get_latest_definition()
			return result
		except Exception: 
			return None
		
class Types:
	
	@staticmethod
	def module() -> Module:
		from ..preprocessing.core import GlobalContext
		try:
			result = GlobalContext.inference["types"].table
			return result
		except Exception:
			return None
	
	@staticmethod
	def get_type(type_name: str) -> Optional[ClassDefinition]:
		try: 
			result = Types.module().classes[type_name].get_latest_definition()
			return result
		except Exception: 
			return None

class Future:

	@staticmethod
	def module() -> Module:
		from ..preprocessing.core import GlobalContext
		try:
			result = GlobalContext.inference["__future__"].table
			return result
		except Exception:
			return None
	
	@staticmethod
	def get_type(type_name: str) -> Optional[ClassDefinition]:
		try: 
			result = Future.module().classes[type_name].get_latest_definition()
			return result
		except Exception: 
			return None

class CollectionsAbc:

	@staticmethod
	def module() -> Module:
		from ..preprocessing.core import GlobalContext
		try:
			result = GlobalContext.inference["collections.abc"].table
			return result
		except Exception:
			return None
	
	@staticmethod
	def get_type(type_name: str) -> Optional[ClassDefinition]:
		try: 
			result = CollectionsAbc.module().classes[type_name].get_latest_definition()
			return result
		except Exception: 
			return None