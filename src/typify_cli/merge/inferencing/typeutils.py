from __future__ import annotations
from typing import Optional

import ast

from .expression import TypeExpr
from .commons import (
	Typing,
	Builtins, 
	Singletons,
	Checker
)
from ..preprocessing.instance_utils import (
	ReferenceSet,
	Instance
)
from ..preprocessing.symbol_table import (
	ClassDefinition
)

class TypeUtils:

	@staticmethod
	def type_expr_from_refset(refset: ReferenceSet):
		type_exprs = []
		for ref in refset:
			type_exprs.append(ref.as_type())
		return TypeUtils.unify_from_exprs(type_exprs)

	#TODO: call __init__ so attributes of the instance are available
	@staticmethod
	def instantiate_from_type_expr(unified_type_expr: TypeExpr) -> ReferenceSet:
		if Checker.match_origin(unified_type_expr.base, Typing.get_type("Union")):
			result = ReferenceSet()
			for typeexpr in unified_type_expr.args:
				result.update(TypeUtils.instantiate_from_type_expr(typeexpr))
			return result
		elif Checker.match_origin(unified_type_expr.base, Typing.get_type("Any")):
			return ReferenceSet()
		elif Checker.match_origin(unified_type_expr.base, Builtins.get_type("NoneType")):
			return ReferenceSet(Singletons.get("None"))
		elif Checker.match_origin(unified_type_expr.base, Typing.get_type("Optional")):
			result = ReferenceSet(Singletons.get("None"))
			unified = TypeUtils.unify_from_exprs(unified_type_expr.args)
			result.update(TypeUtils.instantiate_from_type_expr(unified))
			return result
		elif Checker.match_origin(unified_type_expr.base, Builtins.get_type("bool")):
			return ReferenceSet(
				Singletons.get("True"), 
				Singletons.get("False")
			)
		else:
			if not unified_type_expr.base: return ReferenceSet()

			instance = TypeUtils.instantiate_with_args(
				unified_type_expr.base, 
				unified_type_expr.args
			)
			return ReferenceSet(instance)

	@staticmethod
	def unify_from_exprs(type_exprs: Optional[list[TypeExpr]] = None) -> TypeExpr:
		union_def = Typing.get_type("Union")
		any_def   = Typing.get_type("Any")

		if not type_exprs:
			return TypeExpr(any_def)

		normed = [t.strip() for t in type_exprs if t and t.base is not None]

		def unify_one(t: TypeExpr) -> TypeExpr:
			t = t.strip()
			if t.base == union_def:
				flat: list[TypeExpr] = []
				for a in t.args:
					ua = unify_one(a)
					if ua.base == union_def:
						for x in ua.args:
							flat.append(x)
					else:
						flat.append(ua)

				if any(x.base != any_def for x in flat) and any(x.base == any_def for x in flat):
					flat = [x for x in flat if x.base != any_def]

				if not flat:
					return TypeExpr(any_def)
				if len(flat) == 1:
					return flat[0]
				return TypeExpr(union_def, flat).strip()
			else:
				newargs: list[TypeExpr] = []
				for a in t.args:
					ua = unify_one(a)
					newargs.append(ua)
				return TypeExpr(t.base, newargs).strip()

		parts: list[TypeExpr] = []
		for t in normed:
			ut = unify_one(t)
			if ut.base == union_def:
				for x in ut.args:
					parts.append(x)
			else:
				parts.append(ut)

		if any(x.base != any_def for x in parts) and any(x.base == any_def for x in parts):
			parts = [x for x in parts if x.base != any_def]

		if not parts:
			return TypeExpr(any_def)
		if len(parts) == 1:
			return parts[0]
		return TypeExpr(union_def, parts).strip()

	@staticmethod
	def unify(refset: ReferenceSet):
		return TypeUtils.unify_from_exprs([ref.as_type() for ref in refset])

	@staticmethod
	def instantiate_with_args(
		instantiator: ClassDefinition, 
		typeargs: Optional[list[Instance]] = None
	) -> Instance:

		instance = Instance(instantiator)
		instance.update_type_info(instantiator, typeargs)
		return instance

	@staticmethod
	def get_safe(lst, index, default=None):
		return lst[index] if 0 <= index < len(lst) else default
	
	@staticmethod
	def has_complete_return(stmts: list[ast.stmt]) -> bool:
		for stmt in stmts:
			if isinstance(stmt, ast.Return): return True
			elif isinstance(stmt, ast.If):
				then = TypeUtils.has_complete_return(stmt.body)
				orelse = TypeUtils.has_complete_return(stmt.orelse)
				if then and orelse: return True
			elif isinstance(stmt, (ast.For, ast.While)): continue
			elif isinstance(stmt, ast.Try):
				blocks = [stmt.body, stmt.orelse, stmt.finalbody] + [h.body for h in stmt.handlers]
				if all(TypeUtils.has_complete_return(b) for b in blocks if b): return True
			elif isinstance(stmt, ast.With):
				if TypeUtils.has_complete_return(stmt.body): return True
			elif hasattr(ast, "Match") and isinstance(stmt, ast.Match):
				if all(TypeUtils.has_complete_return(case.body) for case in stmt.cases):
					return True
			elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): continue
		return False
