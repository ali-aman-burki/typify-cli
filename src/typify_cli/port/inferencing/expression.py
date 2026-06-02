from __future__ import annotations
from typing import Union

import ast

from ..preprocessing.instance_utils import Instance, ReferenceSet
from ..preprocessing.precollector import PreCollector
from ..preprocessing.symbol_table import ClassDefinition
from .commons import (
    Checker,
    Typing,
	Builtins,
	Singletons
)

class PackedExpr:

	def __init__(
			self,
			base: Instance,
			args: list[PackedExpr] = None
		):

		self.base = base
		self.args = args or []
	
	def __repr__(self):
		prefix = ""
		if self.base:
			if self.base.origin: prefix = self.base.origin.parent.id
			else: prefix = repr(self.base)

		fqn = prefix if prefix else PreCollector.UNVISITED
		strs = []
		for arg in self.args:
			strs.append(repr(arg))
		joined = ", ".join(strs)
		joined = f"[{joined}]" if joined else joined
		return fqn + f"{joined}"

class TypeExpr:

	def __init__(
			self, 
			base: ClassDefinition, 
			args: list[TypeExpr] = None
		):
		self.base = base
		self.args = args or []

	def strip(self) -> TypeExpr:
		new_args = [arg.strip() for arg in self.args]

		if Checker.match_origin(self.base, Typing.get_type("Union")):
			processed = []
			for arg in new_args:
				if arg not in processed:
					processed.append(arg)
			new_args = processed
			if not new_args:
				return TypeExpr(Typing.get_type("Any"))
			if len(new_args) == 1:
				return new_args[0]
			return TypeExpr(self.base, new_args)

		return TypeExpr(self.base, new_args)
	
	def remove_args(self) -> TypeExpr:
		from ..inferencing.typeutils import TypeUtils
		if Checker.match_origin(self.base, Typing.get_type("Union")):
			new_args = [arg.remove_args() for arg in self.args]
			return TypeUtils.unify_from_exprs([TypeExpr(self.base, new_args)])

		return TypeExpr(self.base, [])
	
	def __eq__(self, other: TypeExpr):
		if not isinstance(other, TypeExpr):
			return NotImplemented

		if self.base != other.base:
			return False

		if Checker.match_origin(self.base, Typing.get_type("Union")):
			return set(self.args) == set(other.args)

		if len(self.args) != len(other.args):
			return False
		return all(a == b for a, b in zip(self.args, other.args))

	def __hash__(self):
		is_union = Checker.match_origin(self.base, Typing.get_type("Union"))

		if is_union:
			return hash((self.base, frozenset(self.args)))

		return hash((self.base, tuple(self.args)))

	def __repr__(self):
		fqn = self.base.parent.id if self.base else PreCollector.UNVISITED

		if Checker.match_origin(self.base, Builtins.get_type("NoneType")):
			return "None"
		if Checker.match_origin(self.base, Builtins.get_type("function")):
			return "Callable"

		if self.args:
			any_cls = Typing.get_type("Any")

			def is_any(te: TypeExpr) -> bool:
				return Checker.match_origin(te.base, any_cls)

			if all(is_any(arg) for arg in self.args):
				return fqn

		joined = ", ".join(repr(arg) for arg in self.args)
		joined = f"[{joined}]" if joined else ""
		return fqn + joined
	
class AliasParser:

	@staticmethod
	def filter_concsubs(concsubs: dict):
		from ..inferencing.generics.model import Placeholder

		concsubs: dict[Placeholder, Union[TypeExpr, list[TypeExpr]]] = concsubs

		typevars_with_owner = {
			key.typevar
			for key in concsubs
			if key.owner is not None
		}

		new_concsubs = {
			key: value
			for key, value in concsubs.items()
			if not (key.typevar in typevars_with_owner and key.owner is None)
		}

		return new_concsubs


	@staticmethod
	def annotation_to_typeexpr(
		annotation: Instance, 
		concsubs: dict
	) -> TypeExpr:
		
		from ..inferencing.generics.model import Placeholder
		
		concsubs: dict[Placeholder, Union[TypeExpr, list[TypeExpr]]] = AliasParser.filter_concsubs(concsubs)
		if Checker.is_alias(annotation):
			return AliasParser.resolve_to_type_expr(annotation.packed_expr, concsubs)
		elif Checker.is_typevar(annotation):
			for k, v in concsubs.items():
				if k.typevar == annotation:
					if v != None: return v
			return TypeExpr(Typing.get_type("Any"))
		elif Checker.is_type(annotation):
			return TypeExpr(annotation.origin)
		elif annotation == Singletons.get("None"):
			return TypeExpr(Builtins.get_type("NoneType"))
		else:
			return TypeExpr(Typing.get_type("Any"))

	@staticmethod
	def resolve_to_type_expr(
		packed_expr: PackedExpr, 
		concsubs: dict
	) -> Union[TypeExpr, list[TypeExpr]]:
		
		from ..inferencing.generics.model import Placeholder
		
		concsubs: dict[Placeholder, Union[TypeExpr, list[TypeExpr]]] = concsubs
		if packed_expr.base.instanceof(Typing.get_type("_UnpackGenericAlias")):
			tvt = packed_expr.base.packed_expr.args[0].base
			for k, v in concsubs.items():
				if k.typevar == tvt:
					if v != None: return v
			return []
		elif Checker.is_alias(packed_expr.base):
			base = packed_expr.base.packed_expr.base.origin
			args = []
			for arg in packed_expr.base.packed_expr.args:
				args.append(AliasParser.resolve_to_type_expr(arg, concsubs))
			return TypeExpr(base, args)
		elif Checker.is_type(packed_expr.base):
			targs: list[TypeExpr] = []
			for parg in packed_expr.args:
				result = AliasParser.resolve_to_type_expr(parg, concsubs)
				if isinstance(result, list):
					targs.extend(result)
				else:
					targs.append(result)
			return TypeExpr(packed_expr.base.origin, targs)
		elif Checker.is_typevar(packed_expr.base):
			tv = packed_expr.base
			for k, v in concsubs.items():
				if k.typevar == tv:
					if v != None: return v
			return TypeExpr(Typing.get_type("Any"))
		elif packed_expr.base == Singletons.get("None"):
			return TypeExpr(Builtins.get_type("NoneType"))
		else:
			return TypeExpr(Typing.get_type("Any"))

	#TODO: may need to later uncomment. so far no evidence of incorrect output if not uncommented
	@staticmethod
	def get_packed_expr(resolver, elt: ast.Expr):
		from ..inferencing.resolver import Resolver

		resolver: Resolver = resolver
		relt = resolver.resolve_value(elt)
		if relt: 
			relt = relt.ref()
			# if Checker.is_generic_alias(relt):
			# 	return relt.packed_expr
			# else:
			return PackedExpr(relt)
		return None

	@staticmethod
	def attach(
		resolver, 
		node: ast.Subscript,
		base_inst: Instance,
		genref: Instance, 
	) -> ReferenceSet:
		from ..inferencing.resolver import Resolver

		resolver: Resolver = resolver
		
		args = []
		
		if isinstance(node.slice, ast.Tuple):
			for elt in node.slice.elts:
				resolved = AliasParser.get_packed_expr(resolver, elt)
				if resolved: args.append(resolved)
		else:
			resolved = AliasParser.get_packed_expr(resolver, node.slice)
			if resolved: args.append(resolved)

		genref.packed_expr = PackedExpr(base_inst, args)