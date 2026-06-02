from typing import Union, Optional
import ast
from typing import Any
from .module_meta import ModuleMeta
from .typeexpr import TypeExpr, parse_typeexpr

class PreCollector(ast.NodeVisitor):

	@staticmethod
	def collect_parameter_slots(fdef: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> dict[str, list[str]]:
		args_node = fdef.args
		parameters: dict[str, list[str]] = {}
		for arg in args_node.posonlyargs:
			parameters[arg.arg] = []
		for arg in args_node.args:
			parameters[arg.arg] = []
		for arg in args_node.kwonlyargs:
			parameters[arg.arg] = []
		if args_node.vararg:
			parameters[args_node.vararg.arg] = []
		if args_node.kwarg:
			parameters[args_node.kwarg.arg] = []
		return parameters

	@staticmethod
	def collect_targets(expr: ast.expr) -> dict[ast.expr, tuple[int, int]]:
		targets: dict[ast.expr, tuple[int, int]] = {}

		def visit(node: ast.expr):
			if isinstance(node, (ast.Name, ast.Attribute)):
				targets[node] = (node.lineno, node.col_offset)
			elif isinstance(node, (ast.Tuple, ast.List)):
				for elt in node.elts:
					visit(elt)
			elif isinstance(node, ast.Starred):
				visit(node.value)

		visit(expr)
		return targets

	def __init__(
			self, 
			typemap: dict,
			module_meta: ModuleMeta, 
			typeslots: bool, 
			infer: bool,
			topn: int,
		):
		self.typemap = typemap
		self.module_meta = module_meta
		self.scope_stack: list[str] = []
		self.typeslots = typeslots
		self.infer = infer
		self.topn = topn
		self.in_function = False

		self._imported_names: dict[str, str] = {}
		self._local_env_stack: list[dict[str, TypeExpr]] = []

		self.DEFAULT_GUESS = TypeExpr(typemap.get("default_guess"))

		self._PRIORITY_TYPE_STRS = typemap.get("priority_type_strs", [])
		self._BUILTIN_CALL_GUESS = {
			k: TypeExpr(v) for k, v in typemap.get("builtin_call_guess", {}).items()
		}

		self._INT_TOKENS = set(typemap.get("int_tokens", []))
		self._FLOAT_TOKENS = set(typemap.get("float_tokens", []))
		self._BOOL_PREFIXES = tuple(typemap.get("bool_prefixes", []))
		self._STR_TOKENS = set(typemap.get("str_tokens", []))
		self._BYTES_TOKENS = set(typemap.get("bytes_tokens", []))
		self._LIST_TOKENS = set(typemap.get("list_tokens", []))
		self._SET_TOKENS = set(typemap.get("set_tokens", []))
		self._DICT_TOKENS = set(typemap.get("dict_tokens", []))

		self._priority_types_canon = []
		for s in self._PRIORITY_TYPE_STRS:
			try:
				self._priority_types_canon.append(str(parse_typeexpr(s).canonical()))
			except Exception:
				self._priority_types_canon.append(s)

	def _format_fqn(self) -> str:
		return ".".join(self.scope_stack)

	def _looks_like_type(self, name: str) -> bool:
		"""
		Only consider PascalCase or camelCase as plausible type identifiers.
		Rules:
		  - No underscores.
		  - Must contain at least one uppercase letter.
		  - Must not be ALL_CAPS.
		Examples accepted: 'Request', 'HttpRequest', 'someType', 'X'
		Rejected: 'SOME_VAR', 'some_imported_function', 'value', 'snake_case'
		"""
		if "_" in name:
			return False
		if not any(c.isalpha() for c in name):
			return False
		has_upper = any(c.isupper() for c in name)
		has_lower = any(c.islower() for c in name)
		if not has_upper:
			return False
		# Reject pure ALL_CAPS like 'LOGGER' or 'ID'
		if has_upper and not has_lower:
			return False
		return True

	def _tokenize_name(self, name: str) -> list[str]:
		toks: list[str] = []
		for part in name.split("_"):
			if not part:
				continue
			chunk = []
			last_is_upper = part[0].isupper()
			start = 0
			for i, ch in enumerate(part[1:], 1):
				is_upper = ch.isupper()
				if is_upper and not last_is_upper:
					chunk.append(part[start:i])
					start = i
				last_is_upper = is_upper
			chunk.append(part[start:])
			toks.extend(tok.lower() for tok in chunk if tok)
		return toks

	def _guess_from_name(self, name: str) -> Optional[TypeExpr]:
		low = name.lower()
		for p in self._BOOL_PREFIXES:
			if low.startswith(p):
				return TypeExpr("bool")
		if self._looks_like_type(name):
			return TypeExpr(name)

		toks = self._tokenize_name(name)
		score = {"int": 0, "float": 0, "bool": 0, "str": 0, "bytes": 0, "list": 0, "set": 0, "dict": 0}
		for t in toks:
			if t in self._INT_TOKENS:    score["int"] += 2
			if t in self._FLOAT_TOKENS:  score["float"] += 2
			if t in self._STR_TOKENS:    score["str"] += 2
			if t in self._BYTES_TOKENS:  score["bytes"] += 2
			if t in self._LIST_TOKENS:   score["list"] += 2
			if t in self._SET_TOKENS:    score["set"] += 2
			if t in self._DICT_TOKENS:   score["dict"] += 2
		# simple plural bias → list
		if toks and toks[-1].endswith("s") and toks[-1] not in {"is", "has", "cls"}:
			score["list"] += 1

		best_type, best_val = max(score.items(), key=lambda kv: kv[1])
		return TypeExpr(best_type) if best_val > 0 else None

	def _call_target_name(self, call: ast.Call) -> Optional[str]:
		if isinstance(call.func, ast.Name):
			return call.func.id
		if isinstance(call.func, ast.Attribute):
			return call.func.attr
		return None

	def _guess_from_call(self, call: ast.Call, name_hint: Optional[str] = None) -> Optional[TypeExpr]:
		target = self._call_target_name(call)
		if not target:
			return None
		if target in self._BUILTIN_CALL_GUESS:
			return self._BUILTIN_CALL_GUESS[target]
		if target in self._imported_names:
			orig = self._imported_names[target]
			base = orig.split(".")[-1]
			if self._looks_like_type(base):
				return TypeExpr(orig)

		if self._looks_like_type(target):
			return TypeExpr(target)
		if name_hint:
			n = self._guess_from_name(name_hint)
			if n:
				return n
		return None

	def _guess_from_constant(self, value: Any) -> Optional[TypeExpr]:
		if value is None: return TypeExpr("None")
		if isinstance(value, bool): return TypeExpr("bool")
		if isinstance(value, int): return TypeExpr("int")
		if isinstance(value, float): return TypeExpr("float")
		if isinstance(value, complex): return TypeExpr("complex")
		if isinstance(value, str): return TypeExpr("str")
		if isinstance(value, bytes): return TypeExpr("bytes")
		return None

	def _expr_key(self, expr: ast.AST) -> Optional[str]:
		try:
			if isinstance(expr, (ast.Name, ast.Attribute)):
				return ast.unparse(expr)
		except Exception:
			return None
		return None

	def _lookup_env(self, expr: ast.AST, env: dict[str, TypeExpr]) -> Optional[TypeExpr]:
		key = self._expr_key(expr)
		if key and key in env:
			return env[key]
		return None

	def _guess_from_expr(self, expr: ast.AST, name_hint: Optional[str] = None, env: Optional[dict[str, TypeExpr]] = None) -> TypeExpr:
		if env is not None and isinstance(expr, (ast.Name, ast.Attribute)):
			aliased = self._lookup_env(expr, env)
			if aliased:
				return aliased

		try:
			if isinstance(expr, ast.Constant):
				gt = self._guess_from_constant(expr.value)
				return gt or self.DEFAULT_GUESS

			if isinstance(expr, (ast.List, ast.ListComp)):
				return TypeExpr("list")
			if isinstance(expr, (ast.Tuple,)):
				return TypeExpr("tuple")
			if isinstance(expr, (ast.Set, ast.SetComp)):
				return TypeExpr("set")
			if isinstance(expr, (ast.Dict, ast.DictComp)):
				return TypeExpr("dict")
			if isinstance(expr, ast.GeneratorExp):
				return TypeExpr("generator")

			if isinstance(expr, ast.Call):
				gt = self._guess_from_call(expr, name_hint=name_hint)
				if gt:
					return gt
				return self.DEFAULT_GUESS

			if isinstance(expr, (ast.BinOp, ast.UnaryOp, ast.Compare)):
				if isinstance(expr, ast.Compare):
					return TypeExpr("bool")
				return TypeExpr("int")

			if isinstance(expr, ast.Name):
				gn = self._guess_from_name(expr.id)
				return gn or self.DEFAULT_GUESS

			if isinstance(expr, ast.Attribute):
				last = expr.attr
				if isinstance(last, str):
					# If this attribute matches an imported name, only accept if it looks like a type
					if last in self._imported_names:
						base = self._imported_names[last].split(".")[-1]
						if self._looks_like_type(base):
							return TypeExpr(self._imported_names[last])
					# Otherwise accept only if the attribute itself looks like a type (Pascal/camel)
					if self._looks_like_type(last):
						return TypeExpr(last)
				return self.DEFAULT_GUESS

		except Exception:
			pass
		return self.DEFAULT_GUESS

	def _infer_param_type(self, arg: ast.arg, default_expr: Optional[ast.AST]) -> TypeExpr:
		name = arg.arg

		if self.scope_stack:
			enclosing = self.scope_stack[-1] if self.scope_stack else None
			if name == "self" and enclosing:
				return TypeExpr(enclosing)
			if name == "cls" and enclosing:
				# type[Enclosing]
				return parse_typeexpr(f"type[{enclosing}]")

		# default expression
		if default_expr is not None:
			return self._guess_from_expr(default_expr, name_hint=name)

		# import-similarity: crude heuristic
		low = name.lower()
		best: Optional[str] = None
		for alias, orig in self._imported_names.items():
			base = orig.split(".")[-1]
			low_base = base.lower()
			if low == low_base or low in low_base or low_base in low:
				if best is None or len(base) > len(best):
					best = base
		if best and self._looks_like_type(best):
			return TypeExpr(best)

		# name heuristics
		byname = self._guess_from_name(name)
		if byname:
			return byname

		return self.DEFAULT_GUESS

	def _assign_target_env(self, target: ast.AST, texpr: TypeExpr):
		if not self._local_env_stack:
			return
		env = self._local_env_stack[-1]
		key = self._expr_key(target)
		if key:
			env[key] = texpr
		if isinstance(target, (ast.Tuple, ast.List)):
			for elt in target.elts:
				self._assign_target_env(elt, texpr)

	def _gather_return_guesses(self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> TypeExpr:
		returns: list[TypeExpr] = []

		def guess_expr_with_env(expr: ast.AST, env: dict[str, TypeExpr]) -> TypeExpr:
			if isinstance(expr, (ast.Name, ast.Attribute)):
				t = self._lookup_env(expr, env)
				if t:
					return t
			return self._guess_from_expr(expr, name_hint=ast.unparse(expr) if hasattr(ast, "unparse") else None, env=env)

		def assign_to_env(target: ast.AST, texpr: TypeExpr, env: dict[str, TypeExpr]):
			try:
				key = ast.unparse(target) if isinstance(target, (ast.Name, ast.Attribute)) else None
			except Exception:
				key = None
			if key:
				env[key] = texpr
			if isinstance(target, (ast.Tuple, ast.List)):
				for elt in target.elts:
					assign_to_env(elt, texpr, env)

		def handle_assign(targets: list[ast.AST], value: ast.AST, env: dict[str, TypeExpr]):
			aliased_t: Optional[TypeExpr] = None
			if isinstance(value, (ast.Name, ast.Attribute)):
				aliased_t = self._lookup_env(value, env)
			if aliased_t is None:
				aliased_t = self._guess_from_expr(value, env=env)

			seq = isinstance(value, (ast.Tuple, ast.List))
			elts = value.elts if seq else None
			if seq:
				flat_targets: list[ast.AST] = []
				for t in targets:
					if isinstance(t, (ast.Tuple, ast.List)):
						flat_targets.extend(t.elts)
					else:
						flat_targets.append(t)
				for i, t in enumerate(flat_targets):
					if elts and i < len(elts):
						assign_to_env(t, self._guess_from_expr(elts[i], env=env), env)
					else:
						assign_to_env(t, aliased_t, env)
			else:
				for t in targets:
					assign_to_env(t, aliased_t, env)

		def walk_block(stmts: list[ast.stmt], env: dict[str, TypeExpr]):
			for s in stmts:
				if isinstance(s, ast.Return):
					if s.value is None:
						returns.append(TypeExpr("None"))
					else:
						returns.append(guess_expr_with_env(s.value, env))
				elif isinstance(s, ast.Yield):
					returns.append(TypeExpr("generator"))
				elif isinstance(s, ast.YieldFrom):
					returns.append(TypeExpr("generator"))
				elif isinstance(s, ast.Assign):
					handle_assign(s.targets, s.value, env)
				elif isinstance(s, ast.AnnAssign):
					# Ignore the annotation, just infer from the value
					t = self._guess_from_expr(s.value, env=env) if s.value else self.DEFAULT_GUESS
					assign_to_env(s.target, t, env)
				elif isinstance(s, ast.AugAssign):
					name_hint = ast.unparse(s.target)
					name_based = self._guess_from_name(name_hint) or None
					texpr = name_based if (name_based and name_based.base in {"str", "list", "set", "dict"}) else TypeExpr("int")
					assign_to_env(s.target, texpr, env)
				elif isinstance(s, ast.If):
					walk_block(s.body, env.copy())
					walk_block(s.orelse, env.copy())
				elif isinstance(s, (ast.For, ast.AsyncFor)):
					assign_to_env(s.target, TypeExpr("list"), env)
					walk_block(s.body, env.copy())
					walk_block(s.orelse, env.copy())
				elif isinstance(s, ast.While):
					walk_block(s.body, env.copy())
					walk_block(s.orelse, env.copy())
				elif isinstance(s, ast.Try):
					walk_block(s.body, env.copy())
					for h in s.handlers:
						walk_block(h.body, env.copy())
					walk_block(s.orelse, env.copy())
					walk_block(s.finalbody, env.copy())
				elif isinstance(s, (ast.With, ast.AsyncWith)):
					for item in s.items:
						tname = self._guess_from_expr(
							item.context_expr,
							name_hint=ast.unparse(item.optional_vars) if item.optional_vars else None,
							env=env
						)
						if item.optional_vars:
							assign_to_env(item.optional_vars, tname, env)
					walk_block(s.body, env.copy())
				else:
					pass

		env0: dict[str, TypeExpr] = {}
		walk_block(node.body, env0)

		if returns:
			counts: dict[str, int] = {}
			for c in returns:
				key = str(c.canonical())
				counts[key] = counts.get(key, 0) + 1
			items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0] == "None"))
			return parse_typeexpr(items[0][0]) if items else self.DEFAULT_GUESS

		lowname = node.name.lower()
		if lowname.startswith(("is_", "has_", "can_", "should_")):
			return TypeExpr("bool")
		if lowname.startswith(("iter_", "gen_", "yield_")):
			return TypeExpr("generator")
		if lowname.startswith(("get_", "find_", "read_", "load_", "fetch_")):
			return self.DEFAULT_GUESS
		return TypeExpr("None")

	def _to_canon_str(self, te: TypeExpr) -> str:
		return str(te.canonical())

	def _build_type_list(self, primary: TypeExpr) -> list[str]:
		"""
		Keep existing primary first, then append prioritized common types
		in the requested order, without duplicates, capped by self.topn.
		"""
		out: list[str] = []
		first = self._to_canon_str(primary)
		out.append(first)

		for canon in self._priority_types_canon:
			if canon not in out:
				out.append(canon)
			if len(out) >= max(1, self.topn):
				break

		# In case topn is smaller than list size, truncate.
		if len(out) > max(1, self.topn):
			out = out[:max(1, self.topn)]
		return out

	def visit_Import(self, node: ast.Import):
		# only needed for inference
		if not (self.typeslots and self.infer):
			return
		for alias in node.names:
			name = alias.asname or alias.name.split(".")[-1]
			self._imported_names[name] = alias.name

	def visit_ImportFrom(self, node: ast.ImportFrom):
		if not (self.typeslots and self.infer):
			return
		for alias in node.names:
			export = alias.asname or alias.name
			self._imported_names[export] = alias.name

	def visit_AnnAssign(self, node: ast.AnnAssign):
		from ..preprocessing.instance_utils import ReferenceSet, VSlot
		fqn = self._format_fqn()
		position = (node.target.lineno, node.target.col_offset)

		if self.typeslots:
			self.module_meta.count_map[position] = 1

		h_type: list[str] = []
		if self.typeslots and self.infer:
			env = self._local_env_stack[-1] if (self.in_function and self._local_env_stack) else None
			if node.value is not None:
				ann_te = self._guess_from_expr(node.value, name_hint=ast.unparse(node.target), env=env)
			else:
				ann_te = self.DEFAULT_GUESS
			h_type = self._build_type_list(ann_te)

		vslot = VSlot(
			scope=fqn,
			name=ast.unparse(node.target),
			u_type=ReferenceSet(),
			h_type=h_type
		)

		if self.typeslots:
			self.module_meta.register_vslot(position, vslot)
		self.module_meta.register_vslot_snapshot(position, vslot)

		if self.in_function and self._local_env_stack and h_type:
			self._assign_target_env(node.target, parse_typeexpr(h_type[0]))

	def visit_AugAssign(self, node: ast.AugAssign):
		from ..preprocessing.instance_utils import ReferenceSet, VSlot
		fqn = self._format_fqn()
		position = (node.target.lineno, node.target.col_offset)

		if self.typeslots:
			self.module_meta.count_map[position] = 1

		h_type: list[str] = []
		if self.typeslots and self.infer:
			name_hint = ast.unparse(node.target)
			name_based = self._guess_from_name(name_hint) or None
			guess_te = name_based if (name_based and name_based.base in {"str", "list", "set", "dict"}) else TypeExpr("int")
			h_type = self._build_type_list(guess_te)

		vslot = VSlot(
			scope=fqn,
			name=ast.unparse(node.target),
			u_type=ReferenceSet(),
			h_type=h_type
		)
		if self.typeslots:
			self.module_meta.register_vslot(position, vslot)
		self.module_meta.register_vslot_snapshot(position, vslot)

		if self.in_function and self._local_env_stack and h_type:
			self._assign_target_env(node.target, parse_typeexpr(h_type[0]))

	def visit_Assign(self, node: ast.Assign):
		from ..preprocessing.instance_utils import ReferenceSet, VSlot
		fqn = self._format_fqn()
		env = self._local_env_stack[-1] if (self.in_function and self._local_env_stack) else None

		for bigtarget in node.targets:
			packs = PreCollector.collect_targets(bigtarget)
			for target, position in packs.items():
				if self.typeslots:
					self.module_meta.count_map[position] = 1

				h_type: list[str] = []
				if self.typeslots and self.infer:
					guess_te: Optional[TypeExpr] = None
					# destructuring support
					if isinstance(bigtarget, (ast.Tuple, ast.List)) and isinstance(node.value, (ast.Tuple, ast.List)):
						try:
							target_names = [t for t in PreCollector.collect_targets(bigtarget).keys()]
							if target in target_names:
								idx = target_names.index(target)
								elts = node.value.elts
								if elts and idx < len(elts):
									guess_te = self._guess_from_expr(elts[idx], name_hint=ast.unparse(target), env=env)
						except Exception:
							guess_te = None
					if guess_te is None:
						if isinstance(node.value, (ast.Name, ast.Attribute)) and env is not None:
							aliased = self._lookup_env(node.value, env)
							if aliased:
								guess_te = aliased
					if guess_te is None:
						guess_te = self._guess_from_expr(node.value, name_hint=ast.unparse(target), env=env)
					h_type = self._build_type_list(guess_te)

				vslot = VSlot(
					scope=fqn,
					name=ast.unparse(target),
					u_type=ReferenceSet(),
					h_type=h_type
				)

				if self.typeslots:
					self.module_meta.register_vslot(position, vslot)
				self.module_meta.register_vslot_snapshot(position, vslot)

				if self.in_function and self._local_env_stack and h_type:
					self._assign_target_env(target, parse_typeexpr(h_type[0]))

	def visit_ClassDef(self, node: ast.ClassDef):
		if not hasattr(self, "_class_stack"):
			self._class_stack = []
		self._class_stack.append(node.name)
		self.scope_stack.append(node.name)
		self.generic_visit(node)
		self.scope_stack.pop()
		self._class_stack.pop()

	def visit_FunctionDef(self, node: ast.FunctionDef):
		from ..preprocessing.instance_utils import ReferenceSet, FSlot
		fqn = self._format_fqn()
		scope = fqn
		position = (node.lineno, node.col_offset)
		h_params = PreCollector.collect_parameter_slots(node)

		h_ret: list[str] = []
		if self.typeslots and self.infer:
			args_node = node.args
			pos_defaults = [None] * (len(args_node.args) - len(args_node.defaults)) + list(args_node.defaults)
			posonly_defaults = [None] * len(args_node.posonlyargs)
			kw_defaults = list(args_node.kw_defaults)

			for i, arg in enumerate(args_node.posonlyargs):
				te = self._infer_param_type(arg, posonly_defaults[i] if i < len(posonly_defaults) else None)
				h_params[arg.arg] = self._build_type_list(te)
			for i, arg in enumerate(args_node.args):
				te = self._infer_param_type(arg, pos_defaults[i] if i < len(pos_defaults) else None)
				h_params[arg.arg] = self._build_type_list(te)
			if args_node.vararg:
				te = self._infer_param_type(args_node.vararg, None) or TypeExpr("tuple")
				h_params[args_node.vararg.arg] = self._build_type_list(te)
			for i, arg in enumerate(args_node.kwonlyargs):
				te = self._infer_param_type(arg, kw_defaults[i])
				h_params[arg.arg] = self._build_type_list(te)
			if args_node.kwarg:
				te = self._infer_param_type(args_node.kwarg, None) or TypeExpr("dict")
				h_params[args_node.kwarg.arg] = self._build_type_list(te)

			self._local_env_stack.append({})
			return_ann_te = self._gather_return_guesses(node)
			h_ret = self._build_type_list(return_ann_te)
		else:
			self._local_env_stack.append({}) if self.infer else None

		if self.typeslots:
			self.module_meta.count_map[position] = 1

		fslot = FSlot(
			scope=scope,
			name=node.name,
			u_params={k: ReferenceSet() for k in h_params},
			h_params=h_params,
			u_ret=ReferenceSet(),
			h_ret=h_ret
		)

		if self.typeslots:
			self.module_meta.register_fslot(position, fslot)
		self.module_meta.register_fslot_snapshot(position, fslot)

		self.scope_stack.append(node.name)
		prev_in_function = self.in_function
		self.in_function = True
		self.generic_visit(node)
		self.in_function = prev_in_function
		self.scope_stack.pop()

		if self._local_env_stack:
			self._local_env_stack.pop()

	def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
		self.visit_FunctionDef(node)
