
import ast

from typing import Union, Optional

from ..preprocessing.module_meta import ModuleMeta
from ..preprocessing.core import GlobalContext
from ..utils.errors import safeguard
from .unpacking_utils import (
	TargetEntry,
	PackGroup
)
from ..preprocessing.instance_utils import (
	ReferenceSet,
	Instance
)
from ..preprocessing.symbol_table import (
	Module,
	ClassDefinition,
	FunctionDefinition,
	Name,
	Class,
	Package,
	Library,
	NameDefinition
)
from .commons import (
	Builtins,
	CollectionsAbc,
	Singletons
)

class Resolver:
	def __init__(
			self, 
			module_meta: ModuleMeta,
			symbol: Union[Union[Module, ClassDefinition], FunctionDefinition], 
			namespace: Instance,
		):
		self.module_meta = module_meta
		self.symbol = symbol
		self.namespace = namespace

	@safeguard(lambda: None, "LEGB_lookup")	
	def LEGB_lookup(self, name: str) -> Name:
		current_symbol = self.symbol

		while not isinstance(current_symbol, (Library, Package)):
			if isinstance(current_symbol, Class):
				current_symbol = current_symbol.get_enclosing_symbol()
				continue
			
			scope = GlobalContext.symbol_map.get(current_symbol.get_latest_definition())
			
			if scope: 
				result = scope.names.get(name)
				if result: return result

			current_symbol = current_symbol.get_enclosing_symbol()

		return Builtins.module().names.get(name, None)

	@safeguard(lambda: PackGroup(groups=[], starred=False), "resolve_target")
	def resolve_target(self, expr: ast.expr) -> PackGroup:
		position = (expr.lineno, expr.col_offset)
		defkey = (self.module_meta.table, position)

		if isinstance(expr, ast.Name):
			symbol_name = self.symbol.get_name(expr.id)
			namespace_name = self.namespace.get_name(expr.id)
			entry = TargetEntry(
				definition=NameDefinition(defkey), 
				namespace_name=namespace_name,
				symbol_name=symbol_name
			)
			entry.namespace_name.set_definition(NameDefinition(defkey))
			entry.symbol_name.set_definition(NameDefinition(defkey))
			return PackGroup(groups=[{entry}], starred=False)

		elif isinstance(expr, (ast.Tuple, ast.List)):
			inner_groups: list[Union[set[TargetEntry], PackGroup]] = []
			for elt in expr.elts:
				subgroup = self.resolve_target(elt)
				inner_groups.append(subgroup)
			return PackGroup(groups=inner_groups, starred=False)

		elif isinstance(expr, ast.Starred):
			resolved = self.resolve_target(expr.value)
			return PackGroup(groups=resolved.groups, starred=True)

		elif isinstance(expr, ast.Attribute):
			instances = self.resolve_value(expr.value)
			group: set[TargetEntry] = set()
			for instance in instances:
				if expr.attr in instance.names:
					entry = TargetEntry(
						definition=NameDefinition(defkey), 
						namespace_name=instance.names[expr.attr])
					group.add(entry)
				else:
					symbol_name = None
					if instance.origin:
						symbol_name = instance.origin.get_name(expr.attr)
						symbol_name.set_definition(NameDefinition(defkey))
					namespace_name = instance.get_name(expr.attr)
					entry = TargetEntry(
						definition=NameDefinition(defkey), 
						namespace_name=namespace_name,
						symbol_name=symbol_name
					)
					entry.namespace_name.set_definition(NameDefinition(defkey))
					group.add(entry)
			return PackGroup(groups=[group], starred=False)
		else:
			return PackGroup(groups=[], starred=False)

	#TODO: need support for comprehensions, generators 
	#TODO: need support for literal types i.e Literal[...]
	# @safeguard(lambda: ReferenceSet(), "resolve_value")
	def resolve_value(self, node: ast.Expr) -> ReferenceSet:
		from ..inferencing.call_dispatcher import CallDispatcher
		from ..inferencing.typeutils import TypeUtils
		from ..inferencing.desugar import Desugar
		
		if isinstance(node, ast.Constant):
			type_name = type(node.value).__name__
			singname = ast.unparse(node)
			singleton = Singletons.get(singname)

			if singleton: 
				instance = singleton
			else:
				instance = TypeUtils.instantiate_with_args(Builtins.get_type(type_name))

			instance.cval = node.value
			return ReferenceSet(instance)
		
		elif isinstance(node, ast.JoinedStr):
			typeclass = Builtins.get_type("str")
			instance = TypeUtils.instantiate_with_args(typeclass)
			return ReferenceSet(instance)
		
		elif isinstance(node, ast.List):
			typeclass = Builtins.get_type("list")
			typeargs = []
			for elt in node.elts:
				resolved = self.resolve_value(elt)
				unified = TypeUtils.unify(resolved)
				typeargs.append(unified)
			
			instance = TypeUtils.instantiate_with_args(typeclass, [TypeUtils.unify_from_exprs(typeargs)])
			return ReferenceSet(instance)
		
		elif isinstance(node, ast.Set):
			typeclass = Builtins.get_type("set")
			typeargs = []
			for elt in node.elts:
				resolved = self.resolve_value(elt)
				unified = TypeUtils.unify(resolved)
				typeargs.append(unified)
			
			instance = TypeUtils.instantiate_with_args(typeclass, [TypeUtils.unify_from_exprs(typeargs)])
			return ReferenceSet(instance)
		
		elif isinstance(node, ast.Tuple):
			typeclass = Builtins.get_type("tuple")
			store = []
			typeargs = []
			for elt in node.elts:
				resolved = self.resolve_value(elt)
				unified = TypeUtils.unify(resolved)
				typeargs.append(unified)
				store.append(resolved)
			instance = TypeUtils.instantiate_with_args(typeclass, typeargs)
			instance.store = store
			return ReferenceSet(instance)
		
		elif isinstance(node, ast.Dict):
			typeclass = Builtins.get_type("dict")
			keyargs = []
			valueargs = []
			for elt in node.keys:
				resolved = self.resolve_value(elt)
				unified = TypeUtils.unify(resolved)
				keyargs.append(unified)
			for elt in node.values:
				resolved = self.resolve_value(elt)
				unified = TypeUtils.unify(resolved)
				valueargs.append(unified)

			instance = TypeUtils.instantiate_with_args(
				typeclass, 
				[TypeUtils.unify_from_exprs(keyargs), TypeUtils.unify_from_exprs(valueargs)]
			)
			return ReferenceSet(instance)
		
		elif isinstance(node, ast.Call):
			dispatcher = CallDispatcher(self, node)
			result = dispatcher.dispatch()
			return result

		elif isinstance(node, ast.Name):
			name = self.LEGB_lookup(node.id)
			if name: return name.get_plausible_refset().copy()
			return ReferenceSet()
		
		elif isinstance(node, ast.Attribute):
			value_references = self.resolve_value(node.value)
			result = ReferenceSet()
			for ref in value_references:
				namet = ref.attribute_lookup(node.attr)
				if namet:
					result.update(namet.get_plausible_refset())
			return result if result else ReferenceSet()
		elif isinstance(node, ast.IfExp):
			body_refs = self.resolve_value(node.body)
			orelse_refs = self.resolve_value(node.orelse)

			result = ReferenceSet()
			result.update(body_refs)
			result.update(orelse_refs)
			
			return result
		else:
			return Desugar.resolve(node, self)
	
	def assign(self, target: ast.expr, value: ast.expr) -> None:
		from ..inferencing.desugar import Desugar

		def _has_starred(t: ast.AST) -> bool:
			if isinstance(t, (ast.Tuple, ast.List)):
				return any(isinstance(e, ast.Starred) or _has_starred(e) for e in t.elts)
			return isinstance(t, ast.Starred)

		if isinstance(target, ast.Subscript):
			call = Desugar.setitem_call(target, value)
			self.resolve_value(call)
			return

		if isinstance(target, (ast.Tuple, ast.List)) and isinstance(value, (ast.Tuple, ast.List)):
			if not _has_starred(target) and len(target.elts) == len(value.elts):
				for t_i, v_i in zip(target.elts, value.elts):
					self.assign(t_i, v_i)
				return

		resolved_target = self.resolve_target(target)
		resolved_value  = self.resolve_value(value)
		self.process_name_binding(resolved_target, resolved_value)
	
	@safeguard(lambda: None, "process_name_binding")
	def process_name_binding(self, resolved_target: PackGroup, resolved_value: ReferenceSet):
		from ..inferencing.typeutils import TypeUtils
		from ..inferencing.expression import TypeExpr

		ListType  = Builtins.get_type("list")
		TupleType = Builtins.get_type("tuple")

		def _leaf_entries(group) -> list[TargetEntry]:
			out = []
			if isinstance(group, PackGroup):
				for g in group.groups:
					out.extend(_leaf_entries(g))
			else:
				out.extend(list(group))
			return out

		def _top_slots(groups: list) -> tuple[Optional[int], int, int]:
			star_idx = None
			for i, g in enumerate(groups):
				if isinstance(g, PackGroup) and g.starred and star_idx is None:
					star_idx = i
			pre = star_idx if star_idx is not None else len(groups)
			post = 0 if star_idx is None else len(groups) - star_idx - 1
			return star_idx, pre, post

		per_target_updates: dict[TargetEntry, ReferenceSet] = {}

		rhs_is_empty = True
		for _ in resolved_value:
			rhs_is_empty = False
			break

		leaf_count = len(_leaf_entries(resolved_target))

		for ref in resolved_value:
			reftype = ref.as_type()
			groups = resolved_target.groups
			star_idx, pre_slots, post_slots = _top_slots(groups)

			def _bind_one_slot(slot_group, element_refs: Optional[ReferenceSet]):
				chosen = element_refs if element_refs is not None else resolved_value.copy()
				if isinstance(slot_group, PackGroup) and not slot_group.starred:
					self.process_name_binding(slot_group, chosen)
				else:
					for entry in _leaf_entries(slot_group):
						entry.definition.refset.update(chosen)
						if entry not in per_target_updates:
							per_target_updates[entry] = ReferenceSet()
						per_target_updates[entry].update(chosen)

			if leaf_count == 1 and star_idx is None:
				for group in groups:
					_bind_one_slot(group, None)
				continue

			if ref.instanceof(TupleType) and ref.store:
				n = len(ref.store)

				def _element_at(idx: int) -> Optional[ReferenceSet]:
					if 0 <= idx < n:
						return ref.store[idx]
					if len(reftype.args) > idx:
						return TypeUtils.instantiate_from_type_expr(reftype.args[idx])
					return None

				for i, group in enumerate(groups):
					if isinstance(group, PackGroup) and group.starred:
						start = min(max(pre_slots, 0), n)
						end   = min(max(n - post_slots, 0), n)
						slice_refs = [ref.store[j] for j in range(start, end)] if start <= end else []

						elem_types = [TypeUtils.unify(rs) for rs in slice_refs]
						list_elem  = TypeUtils.unify_from_exprs(elem_types) if elem_types else (
							TypeUtils.unify_from_exprs(reftype.args[pre_slots: max(len(reftype.args)-post_slots, pre_slots)])
							if getattr(reftype, "args", None) else TypeUtils.unify_from_exprs([])
						)
						list_inst = TypeUtils.instantiate_with_args(ListType, [list_elem])
						try:
							list_inst.store = slice_refs
						except Exception:
							pass
						_bind_one_slot(group, ReferenceSet(list_inst))
					else:
						if star_idx is None:
							idx = i
						elif i < star_idx:
							idx = i
						else:
							after_offset = i - star_idx - 1
							idx = max(n - post_slots + after_offset, 0)
						_bind_one_slot(group, _element_at(idx))

			elif ref.instanceof(CollectionsAbc.get_type("Iterable")) and (
				star_idx is not None or leaf_count > 1
			):
				elem_refs = None

				if ref.instanceof(Builtins.get_type("str")):
					elem_refs = TypeUtils.instantiate_from_type_expr(TypeExpr(Builtins.get_type("str")))
				elif ref.instanceof(Builtins.get_type("bytes")) or ref.instanceof(Builtins.get_type("bytearray")):
					IntType = Builtins.get_type("int")
					elem_refs = TypeUtils.instantiate_from_type_expr(TypeExpr(IntType))
				elif ref.instanceof(Builtins.get_type("dict")):
					if len(reftype.args) >= 1:
						elem_refs = TypeUtils.instantiate_from_type_expr(reftype.args[0])
				elif ref.instanceof(Builtins.get_type("set")) or ref.instanceof(Builtins.get_type("frozenset")):
					if len(reftype.args) >= 1:
						elem_refs = TypeUtils.instantiate_from_type_expr(reftype.args[0])

				if elem_refs is None:
					if reftype.args:
						elem_type_expr = reftype.args[0]
						elem_refs = TypeUtils.instantiate_from_type_expr(elem_type_expr)
					else:
						elem_refs = ReferenceSet()

				list_inst = TypeUtils.instantiate_with_args(ListType, [TypeUtils.unify(elem_refs)])

				for i, group in enumerate(groups):
					if isinstance(group, PackGroup) and group.starred:
						_bind_one_slot(group, ReferenceSet(list_inst))
					else:
						_bind_one_slot(group, elem_refs)

			else:
				for group in groups:
					_bind_one_slot(group, None)

		if rhs_is_empty:
			for entry in _leaf_entries(resolved_target):
				if entry not in per_target_updates:
					per_target_updates[entry] = ReferenceSet() 

		for entry, refset in per_target_updates.items():
			pos = (entry.definition.position[0], entry.definition.position[1])
			entry.namespace_name.set_definition(entry.definition)
			if entry.symbol_name:
				ndef = NameDefinition((entry.definition.module, entry.definition.position))
				ndef.refset.update(refset)
				entry.symbol_name.merge_definition(ndef)

			self.module_meta.safe_update_vslot(pos, refset.copy())
			self.module_meta.update_count_map(pos)
