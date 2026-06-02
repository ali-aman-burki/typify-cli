from typing import Union
import ast
import copy

from ..preprocessing.module_meta import ModuleMeta
from .function_utils import FunctionUtils
from ..preprocessing.dependency_utils import DependencyUtils
from .mro import MROBuilder
from .resolver import Resolver
from .typeutils import TypeUtils
from ..preprocessing.core import GlobalContext
from ..utils.errors import safeguard
from .annotation_utils import (
	DeferredAnnotations,
	Varnotation,
	AnnotationUtils
)
from .expression import (
    TypeExpr, 
    AliasParser
)
from .commons import (
	Builtins,
	Future,
	Singletons,
	ArgTuple,
	Checker,
)
from ..preprocessing.symbol_table import (
	Module,
	ClassDefinition,
	FunctionDefinition,
	NameDefinition,
	CallFrame
)

from ..preprocessing.instance_utils import (
	Instance,
	ReferenceSet,
	VSlot
)

class Executor(ast.NodeVisitor):
	def __init__(
		self, 
		module_meta: ModuleMeta,
		symbol: Union[Module, ClassDefinition, FunctionDefinition],
		namespace: Union[Instance, CallFrame], 
		caller: Instance,
		arguments: dict[str, ArgTuple],
		tree: ast.AST,
		deferred_annotations: DeferredAnnotations = None,
	):
		from ..inferencing.generics.utils import GenericUtils

		self.module_meta = module_meta
		self.symbol = symbol
		self.namespace = namespace
		self.caller = caller
		self.tree = tree

		self.import_stmt_count = 0

		self.returns = ReferenceSet()
		self.resolver = Resolver(
			self.module_meta, 
			self.symbol, 
			self.namespace,
		)

		self.deferred_annotations = deferred_annotations or DeferredAnnotations()
		fobject = GlobalContext.function_object_map.get(self.symbol)

		if fobject:
			fobject.concsubs = {}
			
			position = (fobject.tree.lineno, fobject.tree.col_offset)

			for argname in arguments:
				argtuple = arguments[argname]
				refset = argtuple.refset
				defkey = argtuple.defkey

				namespace_name = self.namespace.get_name(argname)
				symbol_name = self.symbol.get_name(argname)

				ndef = NameDefinition(defkey)
				ndef.refset.update(refset)
				namespace_name.set_definition(ndef)
				merged = symbol_name.merge_definition(ndef)
				annotation = fobject.parameters[argname].annotation
				is_vararg = fobject.parameters[argname].is_vararg

				if annotation:
					type_to_use = refset.as_type()
					if is_vararg:
						type_to_use = TypeUtils.unify_from_exprs(type_to_use.args)

					fobject.concsubs.update(
						GenericUtils.build_ownerless_concsubs(
							annotation,
							type_to_use,
							fobject.concsubs
						)
					)
					if caller:
						GenericUtils.register_annotation(
							annotation=annotation,
							type_expr=type_to_use,
							classdef=self.symbol.get_enclosing_class_definition(),
							genconstruct=caller.genconstruct,
						)
				
				self.module_meta.safe_update_fslot_args(position, argname, merged.refset)
			
		enclosing = None
		enclosing_concsubs = {}
		self.concsubs = {}
		
		current = self.symbol.parent
		while current and not isinstance(current, Module):
			if isinstance(current, FunctionDefinition):
				enclosing = GlobalContext.function_object_map.get(current)
				if enclosing: enclosing_concsubs = enclosing.concsubs
				break
			current = current.parent

		if fobject:
			self.concsubs = fobject.concsubs = enclosing_concsubs | fobject.concsubs
	
	def execute(self) -> ReferenceSet: 
		from ..inferencing.generics.utils import GenericUtils
		
		fobject = GlobalContext.function_object_map.get(self.symbol)

		if isinstance(self.namespace, CallFrame) and FunctionUtils.is_stub(fobject.tree):
			position = (fobject.tree.lineno, fobject.tree.col_offset)
			if fobject.return_annotation and fobject.return_annotation.instantiator:
				if self.caller:
					gencons = self.caller.genconstruct.get(self.symbol.get_enclosing_class_definition())
					if gencons:
						self.concsubs.update(gencons.concsubs)
				type_expr = TypeUtils.unify_from_exprs(
					[AliasParser.annotation_to_typeexpr(fobject.return_annotation, self.concsubs)]
				)
				result = TypeUtils.instantiate_from_type_expr(type_expr)
				self.returns.update(result)
				self.symbol.refset.update(result)
				self.module_meta.safe_update_fslot_return(position, self.symbol.refset)
				self.module_meta.update_count_map(position)

				return self.returns

		try:
			self.visit(self.tree)
		except (RecursionError, UnicodeError):
			return self.returns
		
		if isinstance(self.namespace, CallFrame):
			position = (fobject.tree.lineno, fobject.tree.col_offset)
			if not TypeUtils.has_complete_return(self.tree.body):
				self.returns.add(Singletons.get("None"))
				self.symbol.refset.add(Singletons.get("None"))
			
			if fobject.return_annotation and fobject.return_annotation.instantiator and self.caller:
				GenericUtils.register_annotation(
					annotation=fobject.return_annotation,
					type_expr=self.returns.as_type(),
					classdef=self.symbol.get_enclosing_class_definition(),
					genconstruct=self.caller.genconstruct
				)

			self.module_meta.safe_update_fslot_return(position, self.symbol.refset)
			self.module_meta.update_count_map(position)

		return self.returns

	def visit_Return(self, node):
		resolved = self.resolver.resolve_value(node.value)
		new = ReferenceSet()
		for r in resolved:
			if not any(repr(r) == repr(n) for n in self.symbol.refset):
				new.add(r)
			if not any(repr(r) == repr(n) for n in self.returns):
				new.add(r)

		self.symbol.refset.update(new)
		self.returns.update(new)

	def visit_Import(self, node):
		position = (node.lineno, node.col_offset)
		defkey = (self.module_meta.table, position)
		
		self.import_stmt_count += 1

		for alias in node.names:
			name = alias.asname if alias.asname else alias.name.split(".")[0]
			self.symbol.get_name(name).merge_definition(NameDefinition(defkey))
			self.namespace.get_name(name).set_definition(NameDefinition(defkey))

			object_chain = DependencyUtils.resolve_module_objects(
				defkey, 
				alias.name
			)
			if not object_chain:
				deftable = NameDefinition(defkey)
				self.symbol.get_name(name).merge_definition(deftable)
				self.namespace.get_name(name).merge_definition(deftable)
				continue
			
			deftable = NameDefinition(defkey)
			deftable.refset.add(object_chain[-1] if alias.asname else object_chain[0])
			self.symbol.get_name(name).merge_definition(deftable)
			self.namespace.get_name(name).merge_definition(deftable)

		self.generic_visit(node)
	
	def visit_ImportFrom(self, node):
		position = (node.lineno, node.col_offset)
		defkey = (self.module_meta.table, position)
		
		self.import_stmt_count += 1

		object_chain = DependencyUtils.resolve_module_objects(
			defkey,
			node.module, node.level
		)
		
		if node.names[0].name == "*":
			if not object_chain: return
			for name in object_chain[-1].names.values():
				if not name.id.startswith("_"):
					lat_def = NameDefinition(defkey)
					lat_def.refset = name.get_plausible_refset().copy()
					self.namespace.get_name(name.id).set_definition(lat_def)
		else:
			for alias in node.names:
				name = alias.asname if alias.asname else alias.name
				self.symbol.get_name(name).merge_definition(NameDefinition(defkey))
				self.namespace.get_name(name).set_definition(NameDefinition(defkey))
				
				if not object_chain: 
					deftable = NameDefinition(defkey)
					self.symbol.get_name(name).merge_definition(deftable)
					self.namespace.get_name(name).merge_definition(deftable)
					return
				
				if alias.name in object_chain[-1].names:
					mname = object_chain[-1].names[alias.name]
					
					lat_def = NameDefinition(defkey)
					lat_def.refset = mname.get_plausible_refset().copy()

					self.symbol.get_name(name).merge_definition(lat_def)
					self.namespace.get_name(name).merge_definition(lat_def)

					if lat_def.refset and self.import_stmt_count == 1 and isinstance(self.symbol, Module):
						fobject = GlobalContext.symbol_map.get(Future.module())
						if fobject:
							annobject = fobject.names["annotations"].get_plausible_refset().ref()
							if lat_def.refset.ref() == annobject:
								self.deferred_annotations.on = True
				else:
					fqn = DependencyUtils.to_absolute_name(
						self.module_meta.table, 
						node.module, 
						node.level
					)
					fqn += f".{alias.name}"
					new_object_chain = DependencyUtils.resolve_module_objects(
						defkey,
						fqn
					)
					if not new_object_chain: continue

					deftable = NameDefinition(defkey)
					deftable.refset.add(new_object_chain[-1])
					self.symbol.get_name(name).merge_definition(deftable)
					self.namespace.get_name(name).merge_definition(deftable)
				
		self.deferred_annotations.compute(self.resolver)
		self.generic_visit(node)

	#TODO: add support for multiple possible candidates for a single base
	@safeguard(lambda: None, "visit_ClassDef")
	def visit_ClassDef(self, class_tree: ast.ClassDef):
		from ..inferencing.generics.utils import GenericUtils

		name = class_tree.name
		position = (class_tree.lineno, class_tree.col_offset)
		defkey = (self.module_meta.table, position)

		class_table = self.symbol.get_class(name)
		entering_symbol = class_table.get_definition(ClassDefinition(defkey))

		builtins_module_object = GlobalContext.symbol_map.get(Builtins.module())
		entering_symbol.bases.clear()
		entering_symbol.genbases.clear()

		for base in class_tree.bases:
			base_inst_set = self.resolver.resolve_value(base)
			if base_inst_set:
				base_inst = base_inst_set.ref()
				if base_inst == Singletons.get("None"): continue

				if Checker.is_alias(base_inst):
					entering_symbol.genbases.append(base_inst)
					base_inst = base_inst.packed_expr.base
				
				entering_symbol.bases.append(base_inst)

		if not entering_symbol.bases:
			if builtins_module_object:
				object_class = builtins_module_object.names.get("object")
				if object_class:
					object_def = object_class.get_latest_definition()
					instance = object_def.refset.ref()
					entering_symbol.bases.append(instance)
			
		gentree = { entering_symbol: GenericUtils.build_gentree(entering_symbol) }
		entering_symbol.genconstruct = GenericUtils.flatten_gentree(gentree)
		
		inside_function = False
		current = self.symbol

		while current:
			if isinstance(current, FunctionDefinition):
				inside_function = True
				break
			current = current.parent

		if not inside_function:
			entering_namespace = GlobalContext.symbol_map.setdefault(
				entering_symbol,
				TypeUtils.instantiate_with_args(
					Builtins.get_type("type"),
					[TypeExpr(entering_symbol)]
				)
			)
		else:
			entering_namespace = TypeUtils.instantiate_with_args(
				Builtins.get_type("type"),
				[TypeExpr(entering_symbol)]
			)
			GlobalContext.symbol_map[entering_symbol] = entering_namespace
		
		entering_namespace.update_type_info(
			Builtins.get_type("type"), 
			[TypeExpr(entering_symbol)]
		)

		entering_namespace.origin = entering_symbol
		Executor(
			module_meta=self.module_meta,
			symbol=entering_symbol,
			namespace=entering_namespace,
			caller=self.caller,
			arguments={},
			tree=ast.Module(class_tree.body, type_ignores=[]),
			deferred_annotations=self.deferred_annotations,
		).execute()

		deftable = NameDefinition(defkey)
		deftable.refset.add(entering_namespace)
		self.symbol.get_name(name).merge_definition(deftable)
		self.namespace.get_name(name).set_definition(deftable)

		entering_symbol.mro = MROBuilder.build_mro(entering_namespace)
		self.deferred_annotations.compute(self.resolver)

	# @safeguard(lambda: None, "visit_FunctionDef")
	def visit_FunctionDef(self, func_tree: Union[ast.FunctionDef, ast.AsyncFunctionDef]):
		from ..preprocessing.instance_utils import FSlot
		from ..preprocessing.precollector import PreCollector
		
		position = (func_tree.lineno, func_tree.col_offset)
		defkey = (self.module_meta.table, position)
		name = func_tree.name

		deftable = NameDefinition(defkey)
		self.symbol.get_name(name).merge_definition(deftable)
		self.namespace.get_name(name).set_definition(deftable)

		function_table = self.symbol.get_function(name)
		function_def = function_table.merge_definition(FunctionDefinition(defkey))

		h_params = PreCollector.collect_parameter_slots(func_tree)
		scope = self.symbol.get_relative_fqn(self.module_meta.table)

		fslot = FSlot(
			scope=scope,
			name=name,
			u_params={ k: ReferenceSet() for k in h_params },
			h_params=h_params,
			u_ret=ReferenceSet(),
			h_ret=[]
		)

		self.module_meta.register_fslot_snapshot(position, fslot)

		if not isinstance(self.namespace, CallFrame):
			func_obj = GlobalContext.function_object_map.setdefault(
				function_def,
				TypeUtils.instantiate_with_args(Builtins.get_type("function"))
			)
		else:
			func_obj = TypeUtils.instantiate_with_args(Builtins.get_type("function"))
			GlobalContext.function_object_map[function_def] = func_obj
		
		func_obj.update_type_info(Builtins.get_type("function"))
		func_obj.origin = function_def
		func_obj.tree = func_tree
		func_obj.parameters = FunctionUtils.collect_parameters(
			func_tree, 
			self.resolver, 
		)

		if func_tree.returns:
			AnnotationUtils.check_and_defer(
				self.deferred_annotations,
				self.resolver,
				func_tree.returns,
				func_obj
			)
		for k, v in func_obj.parameters.items():
			if v.node:
				AnnotationUtils.check_and_defer(
					self.deferred_annotations,
					self.resolver,
					v.node,
					v
				)

			ndef = NameDefinition(v.defkey)
			ndef.refset = v.refset.copy()
			mdef = function_def.get_name(k).set_definition(ndef)
			
			self.module_meta.safe_update_fslot_args(position, k, mdef.refset)

		deftable = NameDefinition(defkey)
		deftable.refset.add(func_obj)
		self.symbol.get_name(name).merge_definition(deftable)
		self.namespace.get_name(name).merge_definition(deftable)
		self.deferred_annotations.compute(self.resolver)
	
	def visit_AsyncFunctionDef(self, node):
		self.visit_FunctionDef(node)

	def visit_Call(self, node):
		self.resolver.resolve_value(node)
	
	def visit_Subscript(self, node):
		self.resolver.resolve_value(node)

	def visit_Assign(self, node):
		from ..preprocessing.precollector import PreCollector

		value_expr = node.value
		for tgt in node.targets:
			packs = PreCollector.collect_targets(tgt)
			for target, position in packs.items():
				vslot = VSlot(
					scope=self.symbol.get_relative_fqn(self.module_meta.table), 
					name=ast.unparse(target), 
					u_type=ReferenceSet(),
					h_type=[]
				)

				self.module_meta.register_vslot_snapshot(position, vslot)

			self.resolver.assign(tgt, value_expr)
		self.deferred_annotations.compute(self.resolver)

	def visit_AnnAssign(self, node):
		from ..inferencing.generics.utils import GenericUtils

		resolved_value = self.resolver.resolve_value(node.value)
		arefset = self.resolver.resolve_value(node.annotation)
		position = (node.lineno, node.col_offset)

		vslot = VSlot(
			scope=self.symbol.get_relative_fqn(self.module_meta.table), 
			name=ast.unparse(node.target), 
			u_type=ReferenceSet(),
			h_type=[]
		)

		self.module_meta.register_vslot_snapshot(position, vslot)

		if arefset:
			annotation = arefset.ref().resolve_fully(self.resolver)
			if self.caller and not annotation.instanceof(Builtins.get_type("str")):
				GenericUtils.register_annotation(
					annotation=annotation,
					type_expr=resolved_value.as_type(),
					classdef=self.symbol.get_enclosing_class_definition(),
					genconstruct=self.caller.genconstruct,
				)

		to_pass = ast.Constant(ast.unparse(node.annotation))
		if isinstance(node.annotation, ast.Constant):
			if isinstance(node.annotation.value, str):
				to_pass = node.annotation
			 
		AnnotationUtils.check_and_defer(
			self.deferred_annotations, 
			self.resolver, 
			to_pass, 
			Varnotation()
		)

		resolved_target = self.resolver.resolve_target(node.target)
		self.resolver.process_name_binding(resolved_target, resolved_value)
		self.deferred_annotations.compute(self.resolver)
	
	def visit_AugAssign(self, node):
		from ..inferencing.desugar import Desugar
		from ..inferencing.call_dispatcher import CallDispatcher

		position = (node.target.lineno, node.target.col_offset)

		desugared = Desugar.to_dunder(node)
		dispatcher = CallDispatcher(self.resolver, desugared)
		refset = dispatcher.dispatch()

		vslot = VSlot(
			scope=self.symbol.get_relative_fqn(self.module_meta.table), 
			name=ast.unparse(node.target), 
			u_type=ReferenceSet(),
			h_type=[]
		)

		self.module_meta.register_vslot_snapshot(position, vslot)

		if not refset:
			toAssign = ast.Assign(
				targets=[node.target],
				value=ast.BinOp(
					left=copy.deepcopy(node.target),
					op=node.op,
					right=node.value
				)
			)
			ast.copy_location(toAssign, node)
			ast.copy_location(toAssign.value, node)
			toAssign = ast.fix_missing_locations(toAssign)
			self.visit_Assign(toAssign)
		else:
			resolved_target = self.resolver.resolve_target(node.target)
			self.resolver.process_name_binding(resolved_target, refset)
