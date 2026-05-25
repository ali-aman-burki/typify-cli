import ast

from pathlib import Path

from typify_prototype.preprocessing.symbol_table import Module


class ModuleMeta:

    def __init__(
            self,
            src: Path,
            tree: ast.Module,
            trust_annotations: bool,
            last_modified: Path
        ):
        from typify_prototype.preprocessing.instance_utils import VSlot, FSlot

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

    def precollect(self, typeslots: bool) -> None:
        from typify_prototype.preprocessing.precollector import PreCollector
        try:
            PreCollector(self, typeslots).visit(self.tree)
        except (RecursionError, UnicodeError):
            pass

    def snapshot(self) -> tuple[dict, dict]:
        hashable_funcslots = {}
        for position, funcstuff in self.fslots_snapshots.items():
            hashed_params = {p: r.as_type() for p, r in funcstuff.u_params.items()}
            hashable_funcslots[position] = (hashed_params, funcstuff.u_ret.as_type())

        hashable_varslots = {
            position: varstuff.u_type.as_type()
            for position, varstuff in self.vslots_snapshots.items()
        }

        return (hashable_varslots, hashable_funcslots)

    def register_vslot(self, position: tuple[int, int], vslot):
        if position not in self.vslots:
            self.vslots[position] = vslot

    def register_vslot_snapshot(self, position: tuple[int, int], vslot):
        if position not in self.vslots_snapshots:
            self.vslots_snapshots[position] = vslot

    def register_fslot(self, position: tuple[int, int], fslot):
        if position not in self.fslots:
            self.fslots[position] = fslot

    def register_fslot_snapshot(self, position: tuple[int, int], fslot):
        if position not in self.fslots_snapshots:
            self.fslots_snapshots[position] = fslot

    def safe_update_vslot(self, position: tuple[int, int], refset):
        from typify_prototype.preprocessing.instance_utils import ReferenceSet
        refset: ReferenceSet = refset
        if self.vslots:
            self.vslots[position].u_type.update(refset)
        self.vslots_snapshots[position].u_type.update(refset)

    def safe_update_fslot_args(self, position: tuple[int, int], argname: str, refset):
        from typify_prototype.preprocessing.instance_utils import ReferenceSet
        refset: ReferenceSet = refset
        if self.fslots:
            self.fslots[position].u_params[argname] = refset
        self.fslots_snapshots[position].u_params[argname] = refset

    def safe_update_fslot_return(self, position: tuple[int, int], refset):
        from typify_prototype.preprocessing.instance_utils import ReferenceSet
        refset: ReferenceSet = refset
        if self.fslots:
            self.fslots[position].u_ret = refset
        self.fslots_snapshots[position].u_ret = refset

    def __repr__(self):
        return self.table.fqn

    def typeslots(self, merge_buckets: bool = False):
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

        def normalize_union(t: str):
            if not t or not isinstance(t, str) or not t.startswith("Union["):
                return t
            inner = t[len("Union["):-1]
            parts = [p.strip() for p in inner.split(",") if p.strip()]
            return f"Union[{', '.join(sorted(set(parts)))}]"

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
                    seen = set()
                    ordered = []
                    for p in all_parts:
                        if p not in seen:
                            seen.add(p)
                            ordered.append(p)
                    result.append(normalize_union(f"Union[{', '.join(ordered)}]"))
                else:
                    result.append(normalize_union(v1 or v2))
            seen = set()
            unique_result = []
            for t in result:
                if t not in seen:
                    seen.add(t)
                    unique_result.append(t)
            return move_nones_to_end(unique_result)

        buckets = []

        for position, vslot in self.vslots.items():
            u_type = [vslot.u_type.typestring()] if vslot.u_type else []
            type_list = move_nones_to_end(dedup_preserve_order(u_type))
            buckets.append({
                "category": "variable",
                "scope": vslot.scope,
                "name": vslot.name,
                "type": type_list,
                "locations": [[position[0], position[1]]]
            })

        for position, fslot in self.fslots.items():
            u_ret = [fslot.u_ret.typestring()] if fslot.u_ret else []
            ret_type_list = move_nones_to_end(dedup_preserve_order(u_ret))
            buckets.append({
                "category": "return",
                "scope": f"{fslot.scope + '.' if fslot.scope else ''}{fslot.name}",
                "name": fslot.name,
                "type": ret_type_list,
                "locations": [[position[0], position[1]]]
            })

            for param_name, u_param in fslot.u_params.items():
                param_type = [u_param.typestring()] if u_param else []
                param_type_list = move_nones_to_end(dedup_preserve_order(param_type))
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
            buckets = list(merged.values())

        return buckets
