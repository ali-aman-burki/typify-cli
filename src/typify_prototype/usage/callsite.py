from __future__ import annotations
from collections import defaultdict
from .type_expr import TypeExpr, UNKNOWN, union
from .symbol_table import Registry, CallsiteRecord


def apply_callsites(registry: Registry, all_entries: dict[str, dict[str, dict]]) -> None:
    """
    Post-processing pass: write callsite records into Function entries,
    union observed param types back into Function.params and Parameter entries.
    """
    # Group records by callee (def_relpath:def_key)
    by_callee: dict[str, list[CallsiteRecord]] = defaultdict(list)
    for record in registry.callsite_records:
        fi = record.callee_fi
        by_callee[f"{fi.def_relpath}:{fi.def_key}"].append(record)

    for callee_id, records in by_callee.items():
        fi = records[0].callee_fi
        callee_entries = all_entries.get(fi.def_relpath, {})
        func_entry = callee_entries.get(fi.def_key)
        if not func_entry or func_entry.get("node_type") != "Function":
            continue

        # Write each callsite into the Function entry's callsites dict.
        seen: set[str] = set()
        for record in records:
            site_key = f"{record.caller_relpath}:{record.call_key}"
            if site_key in seen:
                continue
            seen.add(site_key)
            func_entry["callsites"][site_key] = {
                "params": {
                    pname: {
                        "usage": str(ptype) if ptype != UNKNOWN else "",
                        "retrieved": {},
                        "type4py": {},
                    }
                    for pname, ptype in record.arg_types.items()
                },
                "type": {
                    "usage": str(fi.return_type) if fi.return_type != UNKNOWN else "",
                    "retrieved": {},
                    "type4py": {},
                },
            }

        # Union observed param types across all callsites.
        param_union: dict[str, TypeExpr] = {}
        for record in records:
            for pname, ptype in record.arg_types.items():
                if ptype != UNKNOWN:
                    param_union[pname] = union(param_union.get(pname, UNKNOWN), ptype)

        # Write unioned types back into Function.params and Parameter entries.
        params_dict = func_entry.get("params", {})
        for pname, unioned_t in param_union.items():
            if unioned_t == UNKNOWN:
                continue
            if pname in params_dict:
                params_dict[pname]["usage"] = str(unioned_t)
            param_key = fi.param_keys.get(pname)
            if param_key:
                param_entry = callee_entries.get(param_key)
                if param_entry and param_entry.get("node_type") == "Parameter":
                    param_entry["type"]["usage"] = str(unioned_t)
