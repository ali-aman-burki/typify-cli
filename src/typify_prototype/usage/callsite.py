from __future__ import annotations
import ast
from collections import defaultdict
from pathlib import Path
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

        # Write unioned types back into Function.params, Parameter entries, and FuncInfo.
        params_dict = func_entry.get("params", {})
        for pname, unioned_t in param_union.items():
            if unioned_t == UNKNOWN:
                continue
            fi.callsite_param_types[pname] = unioned_t
            if pname in params_dict:
                params_dict[pname]["usage"] = str(unioned_t)
            param_key = fi.param_keys.get(pname)
            if param_key:
                param_entry = callee_entries.get(param_key)
                if param_entry and param_entry.get("node_type") == "Parameter":
                    param_entry["type"]["usage"] = str(unioned_t)


def infer_callsite_returns(
    py_path_map: dict[str, Path],
    registry: Registry,
    all_entries: dict[str, dict[str, dict]],
) -> None:
    """
    For each recorded callsite, simulate the callee body with that call's specific argument
    types and write the resulting return type into the callsite's type.usage field.
    """
    from .infer import infer_return_with_args

    # Group records by callee file so each file is parsed at most once.
    by_relpath: dict[str, list[CallsiteRecord]] = defaultdict(list)
    for record in registry.callsite_records:
        by_relpath[record.callee_fi.def_relpath].append(record)

    for relpath, records in by_relpath.items():
        py_path = py_path_map.get(relpath)
        if not py_path:
            continue
        try:
            tree = ast.parse(py_path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue

        # Index function nodes by def_key ("line:col+4")
        func_nodes: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_nodes[f"{node.lineno}:{node.col_offset + 4}"] = node

        callee_entries = all_entries.get(relpath, {})
        seen: set[str] = set()

        for record in records:
            fi = record.callee_fi
            site_key = f"{record.caller_relpath}:{record.call_key}"
            if site_key in seen:
                continue
            seen.add(site_key)

            func_node = func_nodes.get(fi.def_key)
            if not func_node:
                continue
            func_entry = callee_entries.get(fi.def_key)
            if not func_entry or func_entry.get("node_type") != "Function":
                continue
            if site_key not in func_entry.get("callsites", {}):
                continue

            ret_t = infer_return_with_args(func_node, record.arg_types, registry, relpath)
            if ret_t != UNKNOWN:
                func_entry["callsites"][site_key]["type"]["usage"] = str(ret_t)
