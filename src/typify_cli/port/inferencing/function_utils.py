import ast

from typing import Union

from ..utils.logging import logger
from .resolver import Resolver
from .typeutils import TypeUtils
from .expression import TypeExpr
from ..preprocessing.core import GlobalContext
from .commons import (
	Typing, 
	Builtins,
	ParameterEntry,
	ArgTuple,
	ResolvedArg
)
from ..preprocessing.instance_utils import (
	ReferenceSet,
	Instance
)
from .call_stack import CallSignature
from ..preprocessing.symbol_table import CallFrame

class FunctionUtils:
	
	@staticmethod
	def is_stub(func_node: ast.FunctionDef):
		if len(func_node.body) != 1:
			return False

		stmt = func_node.body[0]

		return (
			isinstance(stmt, ast.Expr)
			and isinstance(stmt.value, ast.Constant)
			and stmt.value.value is Ellipsis
		)

	@staticmethod
	def construct_executor(
		caller: Instance,
		fobject: Instance,
		arguments: dict[str, ArgTuple], 
	):
		from ..inferencing.executor import Executor
		
		function_table = fobject.origin
		tree = fobject.tree
		call_frame = CallFrame(f"frame@{function_table.parent.fqn}")
		call_frame.parent = function_table.parent

		mod = call_frame.get_enclosing_module() 
		GlobalContext.symbol_map[function_table] = call_frame
		context_meta = GlobalContext.meta_map[mod]

		executor = Executor(
			module_meta=context_meta,
			symbol=function_table,
			namespace=call_frame, 
			caller=caller,
			arguments=arguments,
			tree=ast.Module(tree.body, type_ignores=[]), 
		)

		return executor

	@staticmethod
	def exec_function(
		fobject: Instance,
		caller: Instance,
		arguments: dict[str, ArgTuple], 
	) -> ReferenceSet:
		sigkey = CallSignature(fobject=fobject, caller=caller, arguments=arguments)
		signature = GlobalContext.call_stack.get(sigkey)

		executor = FunctionUtils.construct_executor(
			caller=signature.caller,
			fobject=signature.fobject, 
			arguments=signature.arguments, 
		)

		if not GlobalContext.call_stack.contains(signature):
			GlobalContext.call_stack.push(signature)
			logger.debug(f"{logger.emoji_map['push']} Pushed: {repr(signature)}")

			signature.returns = executor.execute().copy()

			GlobalContext.call_stack.pop()
			logger.debug(f"{logger.emoji_map['pop']} Popped: {repr(signature)}")

		return signature.returns

	@staticmethod
	def pre_resolve_call_arguments(
		call_node: ast.Call,
		resolver: Resolver,
	) -> tuple[list[ResolvedArg], dict[str, ResolvedArg]]:

		pos: list[ResolvedArg] = []
		for arg_node in call_node.args:
			vals = resolver.resolve_value(arg_node)
			rs = ReferenceSet()
			for inst in vals:
				rs.add(inst)
			pos.append(ResolvedArg(values=vals, refset=rs))

		kw: dict[str, ResolvedArg] = {}
		for kw_node in call_node.keywords:
			if kw_node.arg is None:
				continue
			vals = resolver.resolve_value(kw_node.value)
			rs = ReferenceSet()
			for inst in vals:
				rs.add(inst)
			kw[kw_node.arg] = ResolvedArg(values=vals, refset=rs)

		return pos, kw

	@staticmethod
	def map_call_arguments(
		call_node: ast.Call,
		parameters: dict[str, ParameterEntry],
		resolver: Resolver,
	) -> dict[str, ArgTuple]:
		resolved_args: dict[str, ArgTuple] = {}

		pos_args, kw_args = FunctionUtils.pre_resolve_call_arguments(call_node, resolver)

		vararg_param = next((p for p in parameters.values() if p.is_vararg), None)

		provided_kw_names = set(kw_args.keys())
		positional_param_entries = [
			p for p in parameters.values()
			if not (p.is_vararg or p.is_kwarg or p.is_kwonly)
			and p.name not in provided_kw_names
		]

		n_bindable = min(len(positional_param_entries), len(pos_args))
		for i in range(n_bindable):
			pentry = positional_param_entries[i]
			resolved_args[pentry.name] = ArgTuple(pos_args[i].refset, pentry.defkey)

		extra_pos = pos_args[n_bindable:]
		if vararg_param and extra_pos:
			typeargs = []
			store = []
			for resolved in extra_pos:
				unified = TypeUtils.unify(resolved.values)
				typeargs.append(unified)
				store.append(resolved.values)

			tup_type = Builtins.get_type("tuple")
			instance = TypeUtils.instantiate_with_args(tup_type, typeargs)
			instance.store = store

			rs = ReferenceSet()
			rs.add(instance)
			resolved_args[vararg_param.name] = ArgTuple(rs, vararg_param.defkey)

		for name, res in kw_args.items():
			if name in parameters:
				pentry = parameters[name]
				resolved_args[name] = ArgTuple(res.refset, pentry.defkey)

		for pname, pentry in parameters.items():
			if pname not in resolved_args:
				resolved_args[pname] = ArgTuple(pentry.refset, pentry.defkey)

		ordered_args: dict[str, ArgTuple] = {}
		for pname in parameters.keys():
			ordered_args[pname] = resolved_args[pname]

		return ordered_args

	#TODO: add support *varargs and **kwargs
	@staticmethod
	def collect_parameters(
		fdef: Union[ast.FunctionDef, ast.AsyncFunctionDef], 
		resolver: Resolver,
	) -> dict[str, ParameterEntry]:
		
		args_node = fdef.args
		parameters: dict[str, ParameterEntry] = {}

		def register_arg(
			arg: ast.arg,
			default_value: ast.expr = None,
			*,
			is_posonly=False,
			is_kwonly=False
		) -> ParameterEntry:
			name = arg.arg
			refset = ReferenceSet()
			defkey = (resolver.module_meta.table, (arg.lineno, arg.col_offset))
			
			if default_value is not None:
				refset.update(resolver.resolve_value(default_value))

			entry = ParameterEntry(
				name=name,
				refset=refset,
				defkey=defkey,
				is_posonly=is_posonly,
				is_kwonly=is_kwonly,
				node=arg.annotation
			)
			parameters[name] = entry
			return entry

		posonly_defaults = [None] * (len(args_node.posonlyargs) - len(args_node.defaults)) + args_node.defaults[:len(args_node.posonlyargs)]
		for arg, default in zip(args_node.posonlyargs, posonly_defaults):
			register_arg(arg, default, is_posonly=True)

		regular_defaults = args_node.defaults[-len(args_node.args):] if args_node.defaults else []
		regular_defaults = [None] * (len(args_node.args) - len(regular_defaults)) + regular_defaults
		for arg, default in zip(args_node.args, regular_defaults):
			register_arg(arg, default)

		if args_node.vararg:
			arg = args_node.vararg
			name = arg.arg
			refset = ReferenceSet()
			defkey = (resolver.module_meta.table, (arg.lineno, arg.col_offset))
			
			refset.add(TypeUtils.instantiate_with_args(Builtins.get_type("tuple")))
			parameters[name] = ParameterEntry(
				name=name,
				refset=refset,
				defkey=defkey,
				is_vararg=True,
				node=arg.annotation
			)

		for arg, default in zip(args_node.kwonlyargs, args_node.kw_defaults):
			register_arg(arg, default, is_kwonly=True)

		if args_node.kwarg:
			arg = args_node.kwarg
			name = arg.arg
			refset = ReferenceSet()
			defkey = (resolver.module_meta.table, (arg.lineno, arg.col_offset))

			dict_expr = TypeExpr(Builtins.get_type("dict"), [TypeExpr(Builtins.get_type("str")), TypeExpr(Typing.get_type("Any"))])
			dict_instance = TypeUtils.instantiate_from_type_expr(dict_expr)
			refset.update(dict_instance)
			
			parameters[name] = ParameterEntry(
				name=name,
				refset=refset,
				defkey=defkey,
				is_kwarg=True,
				node=arg.annotation
			)

		return parameters