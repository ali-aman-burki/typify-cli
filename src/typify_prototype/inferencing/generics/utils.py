from collections import deque, OrderedDict
from typing import Union

from typify_prototype.preprocessing.symbol_table import ClassDefinition
from typify_prototype.preprocessing.instance_utils import Instance
from typify_prototype.inferencing.commons import Typing, Checker

from typify_prototype.inferencing.expression import (
    TypeExpr, 
    PackedExpr
)
from typify_prototype.inferencing.generics.model import (
    Placeholder, 
    GenericTree, 
    GenericConstruct
)

class GenericUtils:

	@staticmethod
	def register_annotation(
		annotation: Instance,
		type_expr: TypeExpr,
		classdef: ClassDefinition,
		genconstruct: dict[ClassDefinition, GenericConstruct]
	):
		if Checker.is_typevar(annotation):
			gencons = genconstruct.get(classdef)
			if gencons:
				for placeholder in gencons.subs:
					if placeholder.typevar == annotation:
						GenericUtils.apply_substitution(
							placeholder, 
							type_expr, 
							genconstruct
						)
		elif Checker.is_alias(annotation):
			subst = GenericUtils.build_substitution_map(
				annotation.packed_expr, 
				type_expr,
				classdef, 
				genconstruct 
			)
			for placeholder, value in subst.items():
				GenericUtils.apply_substitution(
					placeholder, 
					value, 
					genconstruct
				)

	@staticmethod
	def build_ownerless_concsubs(
		annotation: Instance,
		type_expr: TypeExpr,
		subs_cache: dict[Placeholder, Union[TypeExpr, list[TypeExpr]]]
	) -> dict[Placeholder, Union[TypeExpr, list[TypeExpr]]]:
		
		if Checker.is_typevar(annotation):
			ph = Placeholder(None, annotation)
			return {
				ph: ph.update_type(subs_cache, type_expr)
			}
		elif Checker.is_alias(annotation):
			return GenericUtils.build_ownerless_substitution_map(
				annotation.packed_expr,
				type_expr
			)
		else:
			return {}
	
	@staticmethod
	def build_ownerless_substitution_map(
		packed_expr: PackedExpr,
		type_expr: TypeExpr,
	) -> dict[Placeholder, Union[TypeExpr, list[TypeExpr]]]:

		placeholder_cache: dict[object, Placeholder] = {}

		def get_ph(tvar) -> Placeholder:
			ph = placeholder_cache.get(tvar)
			if ph is None:
				ph = Placeholder(None, tvar)
				placeholder_cache[tvar] = ph
			return ph

		def merge_into(target: dict[Placeholder, Union[TypeExpr, list[TypeExpr]]],
					newmap: dict[Placeholder, Union[TypeExpr, list[TypeExpr]]]):
			for p, v in newmap.items():
				target[p] = p.update_type(target, v)

		def _build(px: PackedExpr, tx: TypeExpr,
				acc: dict[Placeholder, Union[TypeExpr, list[TypeExpr]]]):
			packed_is_union = Checker.match_origin(px.base.origin, Typing.get_type("Union"))
			type_is_union = Checker.match_origin(tx.base, Typing.get_type("Union"))
			packed_is_typevar = Checker.is_typevar(px.base)

			if packed_is_union and type_is_union:
				for p_branch in px.args:
					for t_branch in tx.args:
						tmp: dict[Placeholder, Union[TypeExpr, list[TypeExpr]]] = {}
						_build(p_branch, t_branch, tmp)
						merge_into(acc, tmp)
				return

			if packed_is_union:
				for branch in px.args:
					tmp: dict[Placeholder, Union[TypeExpr, list[TypeExpr]]] = {}
					_build(branch, tx, tmp)
					merge_into(acc, tmp)
				return

			if type_is_union:
				for branch in tx.args:
					tmp: dict[Placeholder, Union[TypeExpr, list[TypeExpr]]] = {}
					_build(px, branch, tmp)
					merge_into(acc, tmp)
				return

			if packed_is_typevar:
				ph = get_ph(px.base)
				acc[ph] = ph.update_type(acc, tx)
				return

			lenpacked = len(px.args)
			lentx = len(tx.args)
			tindex = 0

			for i in range(lenpacked):
				if tindex >= lentx:
					break

				arg = px.args[i]
				tx_arg = tx.args[tindex]

				if Checker.is_typevar(arg.base):
					ph = get_ph(arg.base)
					acc[ph] = ph.update_type(acc, tx_arg)
					tindex += 1

				elif arg.base.instanceof(Typing.get_type("_UnpackGenericAlias")):
					tvt = arg.base.packed_expr.args[0].base
					ph = get_ph(tvt)

					endcut = lenpacked - i
					remaining = lentx - tindex - (endcut - 1)

					if remaining >= 0:
						slice_ = tx.args[tindex : tindex + remaining]
						acc[ph] = ph.update_type(acc, slice_)
						tindex += len(slice_)

				else:
					tmp: dict[Placeholder, Union[TypeExpr, list[TypeExpr]]] = {}
					_build(arg, tx_arg, tmp)
					merge_into(acc, tmp)
					tindex += 1

		result: dict[Placeholder, Union[TypeExpr, list[TypeExpr]]] = {}
		_build(packed_expr, type_expr, result)
		return result

	@staticmethod
	def build_substitution_map(
		packed_expr: PackedExpr,
		type_expr: TypeExpr,
		classdef: ClassDefinition,
		genconstruct: dict[ClassDefinition, GenericConstruct]
	) -> dict[Placeholder, Union[TypeExpr, list[TypeExpr]]]:

		result: dict[Placeholder, Union[TypeExpr, list[TypeExpr]]] = {}

		packed_is_union = Checker.match_origin(packed_expr.base.origin, Typing.get_type("Union"))
		type_is_union = Checker.match_origin(type_expr.base, Typing.get_type("Union"))
		packed_is_typevar = Checker.is_typevar(packed_expr.base)

		if packed_is_union and type_is_union:
			matches: list[dict[Placeholder, Union[TypeExpr, list[TypeExpr]]]] = []
			for packed_branch in packed_expr.args:
				for type_branch in type_expr.args:
					subst = GenericUtils.build_substitution_map(
						packed_branch, 
						type_branch,
						classdef, 
						genconstruct 
					)
					matches.append(subst)

			for subst in matches:
				for p, v in subst.items():
					result[p] = p.update_type(result, v)

			return result

		if packed_is_union:
			matches = []
			for branch in packed_expr.args:
				subst = GenericUtils.build_substitution_map(
					branch, 
					type_expr,
					classdef, 
					genconstruct
				)
				matches.append(subst)

			for subst in matches:
				for p, v in subst.items():
					result[p] = p.update_type(result, v)

			return result

		if type_is_union:
			for branch in type_expr.args:
				new_result = GenericUtils.build_substitution_map(
					packed_expr, 
					branch,
					classdef, 
					genconstruct 
				)
				for p, v in new_result.items():
					result[p] = p.update_type(result, v)

			return result

		if packed_is_typevar:
			gencons = genconstruct.get(classdef)
			if gencons:
				for p in gencons.subs:
					if p.typevar == packed_expr.base:
						result[p] = p.update_type(result, type_expr)
						break
			return result
	
		lenpacked = len(packed_expr.args)
		lentx = len(type_expr.args)
		tindex = 0

		for i in range(lenpacked):
			if tindex >= lentx:
				break

			arg = packed_expr.args[i]
			tx_arg = type_expr.args[tindex]

			if Checker.is_typevar(arg.base):
				gencons = genconstruct.get(classdef)
				if gencons:
					for p in gencons.subs:
						if p.typevar == arg.base:
							result[p] = p.update_type(result, tx_arg)
							tindex += 1
							break

			elif arg.base.instanceof(Typing.get_type("_UnpackGenericAlias")):
				tvt = arg.base.packed_expr.args[0].base
				gencons = genconstruct.get(classdef)
				for p in gencons.subs:
					if p.typevar == tvt:
						endcut = lenpacked - i
						remaining = lentx - tindex - (endcut - 1)
						if remaining >= 0:
							slice_ = type_expr.args[tindex : tindex + remaining]
							result[p] = p.update_type(result, slice_)
							tindex += len(result[p])
						break

			else:
				new_result = GenericUtils.build_substitution_map(
					arg, 
					tx_arg,
					classdef, 
					genconstruct 
				)
				for p, v in new_result.items():
					result[p] = p.update_type(result, v)
				tindex += 1

		return result

	@staticmethod
	def apply_substitution_to_class_args(
		classdef: ClassDefinition,
		concrete_args: list[TypeExpr],
		flattened: dict[ClassDefinition, GenericConstruct]
	):
		placeholders = list(flattened[classdef].subs.keys())
		binding = GenericUtils.match_type_exprs(placeholders, concrete_args)

		for placeholder, concrete in binding.items():
			GenericUtils.apply_substitution(placeholder, concrete, flattened)

	@staticmethod
	def apply_substitution(
		source: Placeholder,
		value: Union[TypeExpr, list[TypeExpr]],
		flattened: dict[ClassDefinition, GenericConstruct]
	):
		alias_graph: dict[Placeholder, set[Placeholder]] = {}

		for classdef, construct in flattened.items():
			for key, val in construct.subs.items():
				if isinstance(val, list):
					for v in val:
						alias_graph.setdefault(v, set()).add(key)
						alias_graph.setdefault(key, set()).add(v)
				else:
					alias_graph.setdefault(val, set()).add(key)
					alias_graph.setdefault(key, set()).add(val)

		queue = deque([source])
		visited = set([source])

		while queue:
			current = queue.popleft()
			for neighbor in alias_graph.get(current, []):
				if neighbor not in visited:
					visited.add(neighbor)
					queue.append(neighbor)

		for ph in visited:
			classdef = ph.owner
			if classdef in flattened:
				flattened[classdef].concsubs[ph] = ph.update_type(flattened[classdef].concsubs, value)

	@staticmethod
	def flatten_gentree(gentree: dict[ClassDefinition, GenericTree]) -> dict[ClassDefinition, GenericConstruct]:
		flat: dict[ClassDefinition, GenericConstruct] = {}

		for clsdef, ingentree in gentree.items():
			flat[clsdef] = GenericConstruct(
				subs=ingentree.subs,
				concsubs={ph: None for ph in ingentree.subs}
			)

			nested = GenericUtils.flatten_gentree(ingentree.gentree)
			flat.update(nested)

		return flat

	@staticmethod
	def match_type_exprs(
		placeholders: list[Placeholder],
		actual_args: list[TypeExpr]
	) -> dict[Placeholder, Union[TypeExpr, list[TypeExpr]]]:
		
		result = {}
		i = 0
		tvts = [p for p in placeholders if Checker.is_typevartuple(p.typevar)]

		if len(tvts) > 1:
			raise Exception("Multiple TypeVarTuples not supported.")

		for j, ph in enumerate(placeholders):
			if Checker.is_typevartuple(ph.typevar):
				fixed_after = len(placeholders) - (j + 1)
				tvt_len = len(actual_args) - i - fixed_after
				if tvt_len < 0:
					result[ph] = None
					continue

				sliced = actual_args[i:i + tvt_len]
				result[ph] = sliced
				i += tvt_len
			else:
				if i < len(actual_args):
					result[ph] = actual_args[i]
				else:
					result[ph] = None
				i += 1

		return result

	@staticmethod
	def match_placeholders(
		placeholders: list[Placeholder],
		actual_args: list[Placeholder]
	) -> dict[Placeholder, Union[Placeholder, list[Placeholder]]]:
		
		result = {}
		i = 0
		tvts = [p for p in placeholders if Checker.is_typevartuple(p.typevar)]
		
		if len(tvts) > 1:
			raise Exception("Multiple TypeVarTuples not supported.")

		for j, ph in enumerate(placeholders):
			if Checker.is_typevartuple(ph.typevar):
				fixed_after = len(placeholders) - (j + 1)
				tvt_len = len(actual_args) - i - fixed_after
				if tvt_len < 0:
					result[ph] = ph
					continue

				sliced = actual_args[i:i + tvt_len]

				if len(sliced) == 1 and Checker.is_typevartuple(sliced[0].typevar):
					result[ph] = sliced[0]
				else:
					result[ph] = sliced

				i += tvt_len
			else:
				if i < len(actual_args):
					result[ph] = actual_args[i]
				else:
					result[ph] = ph
				i += 1

		return result

	@staticmethod
	def build_gentree(
		classdef: ClassDefinition,
		prev: list[Placeholder] = None,
		visited: set[ClassDefinition] = None,
	) -> GenericTree:
		
		if visited is None: visited = set()
		if classdef in visited: return GenericTree({}, {})

		visited.add(classdef)

		placeholders = GenericUtils.init_placeholders(classdef, classdef.genbases)

		if prev is None: subs = {ph: ph for ph in placeholders}
		else: subs = GenericUtils.match_placeholders(placeholders, prev)

		result = GenericTree(subs, {})

		for base in classdef.genbases:
			if Checker.match_origin(base.packed_expr.base.origin, Typing.get_type("Generic")):
				continue

			base_classdef = base.packed_expr.base.origin
			base_placeholders = GenericUtils.init_placeholders(classdef, [base])

			base_args = []
			for bp in base_placeholders:
				mapped = subs.get(bp, bp)
				if isinstance(mapped, list): base_args.extend(mapped)
				else: base_args.append(mapped)

			result.gentree[base_classdef] = GenericUtils.build_gentree(base_classdef, base_args, visited)

		return result

	@staticmethod
	def collect_typevars(packed_expr: PackedExpr) -> list[Instance]:
		result = []
		if packed_expr.base.instanceof(
			Typing.get_type("TypeVar")
		):
			result.append(packed_expr.base)
		elif packed_expr.base.instanceof(
			Typing.get_type("_UnpackGenericAlias")
		):
			result.append(packed_expr.base.packed_expr.args[0].base)
		
		for arg in packed_expr.args:
			result += GenericUtils.collect_typevars(arg)
		
		return result
	
	@staticmethod
	def init_placeholders(
		owner: ClassDefinition, 
		generic_bases: list[Instance]
	) -> list[Placeholder]:

		for base in generic_bases:
			if Checker.match_origin(base.packed_expr.base.origin, Typing.get_type("Generic")):
				placeholders = GenericUtils.collect_typevars(base.packed_expr)
				return [Placeholder(owner, ph) for ph in placeholders]

		g_placeholders = []
		for base in generic_bases:
			placeholders = GenericUtils.collect_typevars(base.packed_expr)
			g_placeholders.extend([Placeholder(owner, ph) for ph in placeholders])

		unique = list(OrderedDict.fromkeys(g_placeholders))
		return unique