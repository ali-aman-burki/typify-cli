from __future__ import annotations
from pathlib import Path
from typing import Union

import json

class _PathHolder:
	def __init__(self):
		super().__init__()
		self.pathchain: list[Union[Package, Module]] = []

class _PackagingHolder:
	def __init__(self):
		super().__init__()
		self.packages: dict[str, Package] = {}
		self.modules: dict[str, Module] = {}
		self.trust_annotations: bool = False

class _SyntaxingHolder:
	def __init__(self):
		super().__init__()
		self.classes: dict[str, Class] = {}
		self.functions: dict[str, Function] = {}
		self.names: dict[str, Name] = {}

class _LocationHolder:
	def __init__(self):
		super().__init__()
		self.defkey: tuple[Module, tuple[int, int]] = None

class _ReferenceHolder:
	def __init__(self):
		from typify.preprocessing.instance_utils import ReferenceSet

		super().__init__()
		self.refset: ReferenceSet = ReferenceSet()

class Symbol:
	def __init__(self, id: str):
		super().__init__()
		self.id: str = id
		self.fqn: str = ""
		self.parent: Symbol = None
	
	def __repr__(self): return self.fqn if self.fqn else self.id
	def __str__(self): return self.fqn if self.fqn else self.id

	def export_to_json(self, file_path: Path):
			with file_path.open("w", encoding="utf-8") as f:
				json.dump(self.to_dict(), f, indent='\t')	

	def to_dict(self):
		return {}

	def get_relative_fqn(self, relative_to: Symbol) -> str:
		if self is relative_to:
			return ""

		if not self.fqn:
			return self.id
		if not relative_to or not relative_to.fqn:
			return self.fqn

		self_parts = self.fqn.split('.')
		other_parts = relative_to.fqn.split('.')

		common_length = 0
		for a, b in zip(self_parts, other_parts):
			if a == b:
				common_length += 1
			else:
				break

		if common_length == 0:
			return self.fqn

		relative_parts = self_parts[common_length:]

		if not relative_parts:
			return ""

		return '.'.join(relative_parts)


	def get_enclosing_symbol(self):
		result = self.parent
		if isinstance(result, (ClassDefinition, FunctionDefinition)):
			result = result.parent
		return result
	
	def get_enclosing_class_definition(self):
		result = self
		while result and not isinstance(result, ClassDefinition):
			result = result.parent
		return result
	
	def get_enclosing_module(self):
		result = self
		while result and not isinstance(result, Module):
			result = result.get_enclosing_symbol()
		return result
	
	def get_latest_definition(self) -> Symbol:
		return self

class _PackagingSymbol(
	Symbol, 
	_PathHolder,
	_PackagingHolder
):
	def __init__(self, id: str):
		super().__init__(id)

	def to_dict(self):
		data = super().to_dict()
		data["packages"] = {key: value.to_dict() for key, value in self.packages.items()}
		data["modules"] = {key: value.to_dict() for key, value in self.modules.items()}
		return data

	def set_package(self, package: Package, fqn_map: dict):
		self.packages[package.id] = package
		package.parent = self
		package.fqn = f"{self.fqn}.{package.id}" if self.fqn else package.id
		package.pathchain = self.pathchain + [package]
		fqn_map[package.fqn] = package.pathchain

	def set_module(self, module: Module, fqn_map: dict):
		self.modules[module.id] = module
		module.parent = self
		module.fqn = f"{self.fqn}.{module.id}" if self.fqn else module.id
		if module.id == "__init__": module.fqn = self.fqn
		module.pathchain = self.pathchain + [module]
		fqn_map[module.fqn] = module.pathchain

class _SyntaxingSymbol(
	Symbol, 
	_SyntaxingHolder
):
	def __init__(self, id: str):
		super().__init__(id)

	def to_dict(self):
		data = super().to_dict()
		if self.classes: data["classes"] = {key: value.to_dict() for key, value in self.classes.items()}
		if self.functions: data["functions"] = {key: value.to_dict() for key, value in self.functions.items()}
		if self.names: data["names"] = {key: value.to_dict() for key, value in self.names.items()}
		return data

	def get_name(self, id: str) -> Name:
		name = self.names.get(id)
		if not name:
			name = Name(id)
			name.parent = self
			name.fqn = f"{self.fqn}.{id}" if self.fqn else id
			self.names[id] = name
		return name

	def get_class(self, id: str) -> Class:
		cls = self.classes.get(id)
		if not cls:
			cls = Class(id)
			cls.parent = self
			cls.fqn = f"{self.fqn}.{id}" if self.fqn else id
			self.classes[id] = cls
		return cls

	def get_function(self, id: str) -> Function:
		func = self.functions.get(id)
		if not func:
			func = Function(id)
			func.parent = self
			func.fqn = f"{self.fqn}.{id}" if self.fqn else id
			self.functions[id] = func
		return func

class _LocatableSymbol(
	_SyntaxingSymbol, 
	_LocationHolder
):
	def __init__(self, defkey: tuple[Module, tuple[int, int]]):
		super().__init__(f"{defkey[0].fqn}:{defkey[1][0]}:{defkey[1][1]}")
		self.defkey = defkey
		self.module = defkey[0]
		self.position = defkey[1]

class Library(_PackagingSymbol): pass
class Package(_PackagingSymbol): pass
class Module(
	_SyntaxingSymbol, 
	_PathHolder
): pass

class ClassDefinition(_LocatableSymbol): 
	def __init__(self, defkey: tuple[Module, tuple[int, int]]):
		from typify.preprocessing.instance_utils import Instance
		from typify.inferencing.generics.model import GenericConstruct

		super().__init__(defkey)
		self.bases: list[Instance] = []
		self.genbases: list[Instance] = []
		self.mro: list[Instance] = []
		self.genconstruct: dict[ClassDefinition, GenericConstruct] = {}
	
	def to_dict(self):
		base_data = super().to_dict()
		data = {
			"bases": [base.origin.fqn for base in self.bases],
			"mro": [base.origin.fqn for base in self.mro],
		}
		data.update(base_data)
		return data

class FunctionDefinition(
	_LocatableSymbol, 
	_ReferenceHolder
):
	def to_dict(self):
		base_data = super().to_dict()
		data = {
			"return_type": repr(self.refset.as_type())
		}
		data.update(base_data)
		return data

class NameDefinition(
	_LocatableSymbol, 
	_ReferenceHolder
):
	def to_dict(self):
		base_data = super().to_dict()
		data = {
			"type": repr(self.refset.as_type())
		}
		data.update(base_data)
		return data

class CallFrame(
	_SyntaxingSymbol, 
	_ReferenceHolder
): pass
	
class Class(Symbol): 
	def __init__(self, id):
		super().__init__(id)
		self.definitions: dict[str, ClassDefinition] = {}
	
	def to_dict(self):
		data = super().to_dict()
		if self.definitions: data["definitions"] = {key: value.to_dict() for key, value in self.definitions.items()}
		return data

	def set_definition(self, class_def: ClassDefinition):
		class_def.parent = self
		class_def.fqn = self.fqn
		self.definitions[class_def.id] = class_def
		return class_def
	
	def get_definition(self, class_def: ClassDefinition):
		if class_def.id in self.definitions: 
			return self.definitions[class_def.id]
		else: 
			return self.set_definition(class_def)
		
	def get_latest_definition(self) -> ClassDefinition:
		if not self.definitions: return self
		return next(reversed(self.definitions.values()))

class Function(Symbol): 
	def __init__(self, id):
		super().__init__(id)
		self.definitions: dict[str, FunctionDefinition] = {}
	
	def to_dict(self):
		data = super().to_dict()
		if self.definitions: data["definitions"] = {key: value.to_dict() for key, value in self.definitions.items()}
		return data
	
	def set_definition(self, func_def: FunctionDefinition):
		func_def.parent = self
		func_def.fqn = self.fqn
		self.definitions[func_def.id] = func_def
		return func_def

	def merge_definition(self, func_def: FunctionDefinition):
		if func_def.id in self.definitions: 
			self.definitions[func_def.id].refset.update(func_def.refset)
			return self.definitions[func_def.id]
		else: 
			return self.set_definition(func_def)
		
	def get_latest_definition(self) -> FunctionDefinition:
		if not self.definitions: return self
		return next(reversed(self.definitions.values()))

class Name(Symbol): 
	def __init__(self, id):
		super().__init__(id)
		self.definitions: dict[str, NameDefinition] = {}
	
	def to_dict(self):
		data = super().to_dict()
		if self.definitions: data["definitions"] = {key: value.to_dict() for key, value in self.definitions.items()}
		return data
	
	def set_definition(self, name_def: NameDefinition):
		name_def.parent = self
		name_def.fqn = self.fqn
		self.definitions[name_def.id] = name_def
		return name_def

	def merge_definition(self, func_def: NameDefinition):
		if func_def.id in self.definitions: 
			self.definitions[func_def.id].refset.update(func_def.refset)
			return self.definitions[func_def.id]
		else: 
			return self.set_definition(func_def)
		
	def get_latest_definition(self) -> NameDefinition:
		if not self.definitions: return self
		return next(reversed(self.definitions.values()))
	
	def lookup_definition(self, defkey: tuple[Module, tuple[int, int]]) -> NameDefinition:
		key = f"{defkey[0].fqn}:{defkey[1][0]}:{defkey[1][1]}"
		return self.definitions[key]
	
	def get_plausible_refset(self):
		from typify.preprocessing.instance_utils import ReferenceSet

		result = ReferenceSet()
		for definition in self.definitions.values():
			result.update(definition.refset)
		
		result.clean()
		return result