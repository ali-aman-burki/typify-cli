import ast

from pathlib import Path

from .symbol_table import Module

class ModuleMeta:

	def __init__(
			self, 
			src: Path, 
			tree: ast.Module, 
			trust_annotations: bool,
			last_modified: Path
		):
		from typify.preprocessing.instance_utils import VSlot, FSlot
		
		self.src = src
		self.tree = tree
		self.table = Module(src.stem)
		self.trust_annotations = trust_annotations
		self.last_modified = last_modified

		try:
			self.source_text = src.read_text(encoding="utf8")
			self.source_lines = self.source_text.splitlines()
		except Exception:
			self.source_text = ""
			self.source_lines = []

		self.vslots: dict[tuple[int, int], VSlot] = {}
		self.fslots: dict[tuple[int, int], FSlot] = {}
		self.vslots_snapshots: dict[tuple[int, int], VSlot] = {}
		self.fslots_snapshots: dict[tuple[int, int], FSlot] = {}

		self.count_map: dict[tuple[int, int], int] = {}

	def precollect(self, typeslots: bool, infer: bool, topn: int, typemap: dict) -> int:
		from typify.preprocessing.precollector import PreCollector
		try:
			PreCollector(typemap, self, typeslots, infer, topn).visit(self.tree)
		except (RecursionError, UnicodeError):
			pass

		if typeslots:
			return sum(self.count_map.values())
		return 0

	def snapshot(self) -> tuple[dict, dict]:
		hashable_funcslots = {}
		for position, funcstuff in self.fslots_snapshots.items():
			hashed_params = {}
			for p, r in funcstuff.u_params.items():
				hashed_params[p] = r.as_type()
			hashed_returns = funcstuff.u_ret.as_type()

			hashable_funcslots[position] = (hashed_params, hashed_returns)
		
		hashable_varsots = {}
		for position, varstuff in self.vslots_snapshots.items():
			hashable_varsots[position] = varstuff.u_type.as_type()

		return (hashable_varsots, hashable_funcslots)

	def update_count_map(self, position: tuple[int, int]):
		from typify.preprocessing.core import GlobalContext
		if self.count_map.get(position, 0) > 0:
			self.count_map[position] -= 1
			GlobalContext.progress_bar.update()

	def register_vslot(
			self, 
			position: tuple[int, int],
			vslot
		):
		
		if position not in self.vslots: 
			self.vslots[position] = vslot
	
	def register_vslot_snapshot(
			self, 
			position: tuple[int, int],
			vslot
		):
		
		if position not in self.vslots_snapshots: 
			self.vslots_snapshots[position] = vslot

	def register_fslot(
			self, 
			position: tuple[int, int],
			fslot
		):
		
		if position not in self.fslots: 
			self.fslots[position] = fslot

	def register_fslot_snapshot(
			self, 
			position: tuple[int, int], 
			fslot
		):

		if position not in self.fslots_snapshots:
			self.fslots_snapshots[position] = fslot

	def safe_update_vslot(self, position: tuple[int, int], refset):
		from typify.preprocessing.instance_utils import ReferenceSet

		refset: ReferenceSet = refset
		
		if self.vslots:
			self.vslots[position].u_type.update(refset)
		
		self.vslots_snapshots[position].u_type.update(refset)

	def safe_update_fslot_args(self, position: tuple[int, int], argname: str, refset):
		from typify.preprocessing.instance_utils import ReferenceSet

		refset: ReferenceSet = refset

		if self.fslots:
			self.fslots[position].u_params[argname] = refset
		
		self.fslots_snapshots[position].u_params[argname] = refset

	def safe_update_fslot_return(self, position: tuple[int, int], refset):
		from typify.preprocessing.instance_utils import ReferenceSet

		refset: ReferenceSet = refset

		if self.fslots:
			self.fslots[position].u_ret = refset
		
		self.fslots_snapshots[position].u_ret = refset

	def __repr__(self):
		return self.table.fqn
	
	def typeslots(self, topn: int, merge_buckets: bool = False):
		def move_nones_to_end(lst):
			return [x for x in lst if x != "None"] + [x for x in lst if x == "None"]

		def dedup_preserve_order(lst):
			seen = set()
			result = []
			for x in lst:
				if x not in seen:
					seen.add(x)
					result.append(x)
			return result

		def truncate_types(lst):
			"""Trim list to topn elements if topn is set."""
			if topn is not None and len(lst) > topn:
				return lst[:topn]
			return lst

		def normalize_union(t: str):
			if not t or not isinstance(t, str) or not t.startswith("Union["):
				return t
			inner = t[len("Union["):-1]
			parts = [p.strip() for p in inner.split(",") if p.strip()]
			unique_sorted = sorted(set(parts))
			return f"Union[{', '.join(unique_sorted)}]"

		def union_types(t1_list, t2_list):
			max_len = max(len(t1_list), len(t2_list))
			result = []
			for i in range(max_len):
				v1 = t1_list[i] if i < len(t1_list) else None
				v2 = t2_list[i] if i < len(t2_list) else None

				if v1 and v2 and v1 != v2:
					all_parts = []
					for v in (v1, v2):
						if v.startswith("Union["):
							all_parts.extend([p.strip() for p in v[6:-1].split(",") if p.strip()])
						else:
							all_parts.append(v)
					# dedup while preserving order
					seen = set()
					ordered = []
					for p in all_parts:
						if p not in seen:
							seen.add(p)
							ordered.append(p)
					new_type = f"Union[{', '.join(ordered)}]"
					result.append(normalize_union(new_type))
				else:
					result.append(normalize_union(v1 or v2))

			# dedup preserving order again
			seen = set()
			unique_result = []
			for t in result:
				if t not in seen:
					seen.add(t)
					unique_result.append(t)
			unique_result = move_nones_to_end(unique_result)
			return truncate_types(unique_result)

		buckets = []

		for position, vslot in self.vslots.items():
			u_type = [vslot.u_type.typestring()] if vslot.u_type else []
			type_list = move_nones_to_end(dedup_preserve_order(u_type + vslot.h_type))
			type_list = truncate_types(type_list)
			buckets.append({
				"category": "variable",
				"scope": vslot.scope,
				"name": vslot.name,
				"type": type_list,
				"locations": [[position[0], position[1]]]
			})

		for position, fslot in self.fslots.items():
			u_ret = [fslot.u_ret.typestring()] if fslot.u_ret else []
			ret_type_list = move_nones_to_end(dedup_preserve_order(u_ret + fslot.h_ret))
			ret_type_list = truncate_types(ret_type_list)
			buckets.append({
				"category": "return",
				"scope": f"{fslot.scope + '.' if fslot.scope else ''}{fslot.name}",
				"name": fslot.name,
				"type": ret_type_list,
				"locations": [[position[0], position[1]]]
			})

			for param_name, u_param in fslot.u_params.items():
				param_type = [u_param.typestring()] if u_param else []
				param_type_list = move_nones_to_end(
					dedup_preserve_order(param_type + fslot.h_params.get(param_name, []))
				)
				param_type_list = truncate_types(param_type_list)
				buckets.append({
					"category": "argument",
					"scope": f"{fslot.scope + '.' if fslot.scope else ''}{fslot.name}",
					"name": param_name,
					"type": param_type_list,
					"locations": [[position[0], position[1]]]
				})

		if merge_buckets:
			merged = {}
			for b in buckets:
				key_ = (b["name"], b["category"], b["scope"])
				if key_ not in merged:
					merged[key_] = b.copy()
				else:
					existing = merged[key_]
					existing["locations"].extend(b["locations"])
					existing["type"] = union_types(existing["type"], b["type"])
					existing["type"] = truncate_types(existing["type"])
			buckets = list(merged.values())

		return buckets

