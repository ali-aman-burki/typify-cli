from __future__ import annotations
from typing import Union, Optional
from dataclasses import dataclass

import ast

from typify_prototype.preprocessing.symbol_table import (
	Name,
	ClassDefinition,
	FunctionDefinition
)

class ReferenceSet:
	def __init__(self, *reference_list: Instance):
		self.references = dict.fromkeys(reference_list)

	def __repr__(self) -> str: return repr(self.as_type())
	def __len__(self) -> int: return len(self.references)
	def __contains__(self, item: Instance) -> bool: return item in self.references
	def __iter__(self): return iter(self.references)

	def copy(self):
		c = ReferenceSet()
		c.references = self.references.copy()
		return c

	def add(self, reference: Instance):
		self.references[reference] = None

	def update(self, other: ReferenceSet):
		for ref in other:
			self.references[ref] = None
	
	def clean(self):
		seen = {}
		for ref in self.references:
			key = (ref.instantiator, frozenset(ref.names.keys()))
			seen[key] = ref
		self.references = dict.fromkeys(seen.values())

	def ref(self) -> Optional[Instance]:
		if not self.references:
			return None
		return next(reversed(self.references))
	
	def as_type(self):
		from typify_prototype.inferencing.typeutils import TypeUtils
		return TypeUtils.unify(self)
	
	def typestring(self):
		return repr(self.as_type().strip())

class Instance:
	def __init__(self, instantiator: ClassDefinition):
		from typify_prototype.inferencing.generics.model import GenericConstruct, Placeholder
		from typify_prototype.inferencing.expression import PackedExpr, TypeExpr
		from typify_prototype.inferencing.commons import ParameterEntry

		self.instantiator: ClassDefinition = instantiator
		self.names: dict[str, Name] = {}
		self.store: list[ReferenceSet] = []
		self.packed_expr: PackedExpr = None
		self.origin: Union[ClassDefinition, FunctionDefinition] = None
		self.cval = None
		
		self.tree: Union[ast.FunctionDef, ast.AsyncFunctionDef] = None
		self.parameters: dict[str, ParameterEntry] = {}
		self.return_annotation: Instance = None
		self.concsubs: dict[Placeholder, Union[TypeExpr, list[TypeExpr]]] = {}

		self.genconstruct: dict[ClassDefinition, GenericConstruct] = {}
	
	def resolve_fully(self, resolver):
		from typify_prototype.inferencing.commons import Checker, Builtins
		from typify_prototype.inferencing.resolver import Resolver

		resolver: Resolver = resolver

		if self.instanceof(Builtins.get_type("str")):
			node = ast.parse(self.cval, mode='eval').body
			refset = resolver.resolve_value(node)
			if refset:
				ref = refset.ref()
				return ref.resolve_fully(resolver)
		elif Checker.is_alias(self):
			for arg in self.packed_expr.args:
				arg.base = arg.base.resolve_fully(resolver)
			return self
		return self

	def collect_str_objects(self):
		from typify_prototype.inferencing.commons import Checker, Builtins
		
		if self.instanceof(Builtins.get_type("str")):
			return { self }
		elif Checker.is_alias(self):
			result = set()
			for arg in self.packed_expr.args:
				result.update(arg.base.collect_str_objects())
			return result
		return set()
	
	def collect_str_holders(self):
		from typify_prototype.inferencing.commons import Checker, Builtins
		if Checker.is_alias(self):
			result = {}
			for arg in self.packed_expr.args:
				if arg.base.instanceof(Builtins.get_type("str")):
					result[arg] = arg.base.cval
				else:
					result.update(arg.base.collect_str_holders())
			return result
		return {}

	def instanceof(self, *typedefs: Union[ClassDefinition, tuple[ClassDefinition, ...]]) -> bool:
		if not self.instantiator: return False

		typedefs = typedefs[0] if len(typedefs) == 1 and isinstance(typedefs[0], tuple) else typedefs
		mro = [i.origin for i in self.instantiator.mro]
		for td in typedefs:
			if td and td in mro:
				return True

		return False
	
	def attribute_lookup(
			self, 
			attr: str
		) -> Name:
		
		from typify_prototype.inferencing.commons import Checker

		if attr in self.names: return self.names[attr]
		
		if Checker.is_type(self):
			for m in self.instantiator.mro:
				if attr in m.names: return m.names[attr]

			for m in self.origin.mro:
				if attr in m.names: return m.names[attr]
		else:
			for m in self.instantiator.mro:
				if attr in m.names: return m.names[attr]
		
		return None

	def update_type_info(
			self, 
			instantiator: ClassDefinition, 
			typeargs: list = None
		):
		from typify_prototype.inferencing.generics.utils import GenericUtils
		from typify_prototype.inferencing.expression import TypeExpr
		
		typeargs: list[TypeExpr] = typeargs if typeargs else []
		self.instantiator = instantiator

		if self.instantiator:
			self.genconstruct = self.instantiator.genconstruct.copy()
			for k, v in self.genconstruct.items():
				self.genconstruct[k] = v.copy()
			
			GenericUtils.apply_substitution_to_class_args(
				self.instantiator, 
				typeargs, 
				self.genconstruct
			)

	def as_type(self):
		from typify_prototype.inferencing.expression import TypeExpr
		from typify_prototype.inferencing.commons import Typing, Checker

		base = self.instantiator
		args = []

		if self.genconstruct.keys():
			gencons = self.genconstruct[base]
			for k, v in gencons.concsubs.items():
				if Checker.is_typevartuple(k.typevar):
					args.extend(v if v else [])
				else:
					args.append(v if v else TypeExpr(Typing.get_type("Any")))
			
		return TypeExpr(base, args)

	def __repr__(self) -> str:
		return f"instance@{repr(self.as_type())}"
	
	def get_name(self, id: str) -> Name:
		name = self.names.get(id)
		if not name:
			name = Name(id)
			self.names[id] = name
		return name

@dataclass
class VSlot:
	scope: str
	name: str
	u_type: ReferenceSet

@dataclass
class FSlot:
	scope: str
	name: str
	u_params: dict[str, ReferenceSet]
	u_ret: ReferenceSet