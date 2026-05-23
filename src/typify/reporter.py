"""
Output formatting for inference results.
"""
from __future__ import annotations

import json
from typing import List

from .analyzer import ProjectResult, FileResult
from .types import FunctionType


# ANSI colours (disabled automatically if not a TTY)
import sys
_COLOR = sys.stdout.isatty()

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text

def _green(t):  return _c("32", t)
def _yellow(t): return _c("33", t)
def _cyan(t):   return _c("36", t)
def _bold(t):   return _c("1",  t)
def _dim(t):    return _c("2",  t)
def _red(t):    return _c("31", t)


class TextReporter:
    """Human-readable terminal report."""

    def __init__(
        self,
        show_unknown: bool = False,
        show_imports: bool = False,
        group_by_file: bool = True,
    ) -> None:
        self.show_unknown = show_unknown
        self.show_imports = show_imports
        self.group_by_file = group_by_file

    def report(self, project: ProjectResult) -> str:
        lines: List[str] = []
        lines.append(_bold(f"\n{'='*60}"))
        lines.append(_bold(f"  Typify — Type Inference Report"))
        lines.append(_bold(f"  Project: {project.root}"))
        lines.append(_bold(f"{'='*60}\n"))

        if self.group_by_file:
            for fr in project.files:
                lines.extend(self._file_section(fr))
        else:
            lines.extend(self._flat_section(project))

        lines.extend(self._function_returns(project))
        lines.extend(self._class_attrs(project))
        lines.extend(self._stats(project))
        return "\n".join(lines)

    def _file_section(self, fr: FileResult) -> List[str]:
        lines = []
        lines.append(_cyan(f"┌─ {fr.module_name}") + _dim(f"  ({fr.filepath})"))
        if fr.parse_error:
            lines.append(_red(f"│  ✗ Parse error: {fr.parse_error}"))
            lines.append(_cyan("└" + "─" * 58))
            return lines

        seen = set()
        for qname, sym in fr.result.bindings:
            if qname in seen:
                continue
            seen.add(qname)
            t = sym.inferred_type
            if t.is_unknown() and not self.show_unknown:
                continue
            # Skip function types in variable list (shown separately)
            if isinstance(t, FunctionType):
                continue
            color = _green if not t.is_unknown() else _yellow
            lines.append(f"│  {_bold(qname):<40}  {color(str(t))}")

        if not any(True for l in lines if l.startswith("│  ")):
            lines.append(_dim("│  (no inferred bindings)"))

        lines.append(_cyan("└" + "─" * 58))
        return lines

    def _flat_section(self, project: ProjectResult) -> List[str]:
        lines = [_bold("Variables / Bindings"), ""]
        for module, qname, sym in project.all_bindings:
            t = sym.inferred_type
            if t.is_unknown() and not self.show_unknown:
                continue
            if isinstance(t, FunctionType):
                continue
            color = _green if not t.is_unknown() else _yellow
            lines.append(f"  {module}.{qname:<50}  {color(str(t))}")
        return lines

    def _function_returns(self, project: ProjectResult) -> List[str]:
        lines = ["\n" + _bold("Function Return Types"), ""]
        entries = project.function_returns
        if not entries:
            lines.append("  (none)")
            return lines
        for module, fname, rtype in sorted(entries, key=lambda x: (x[0], x[1])):
            color = _green if not rtype.is_unknown() else _yellow
            lines.append(f"  {module}.{fname:<50}  → {color(str(rtype))}")
        return lines

    def _class_attrs(self, project: ProjectResult) -> List[str]:
        lines = ["\n" + _bold("Class Attributes"), ""]
        entries = project.class_attrs
        if not entries:
            lines.append("  (none)")
            return lines
        for module, key, t in sorted(entries, key=lambda x: (x[0], x[1])):
            color = _green if not t.is_unknown() else _yellow
            lines.append(f"  {module}.{key:<50}  {color(str(t))}")
        return lines

    def _stats(self, project: ProjectResult) -> List[str]:
        s = project.stats()
        lines = ["\n" + _bold("─" * 60), _bold("Summary")]
        lines.append(f"  Files analysed   : {s['files']}")
        if s["parse_errors"]:
            lines.append(_red(f"  Parse errors     : {s['parse_errors']}"))
        lines.append(f"  Total bindings   : {s['total_bindings']}")
        lines.append(_green(f"  Inferred         : {s['inferred']}"))
        if s["unknown"]:
            lines.append(_yellow(f"  Unknown          : {s['unknown']}"))
        cov = s["coverage_pct"]
        cov_str = f"{cov}%"
        color = _green if cov >= 70 else (_yellow if cov >= 40 else _red)
        lines.append(f"  Inference coverage: {color(cov_str)}")
        lines.append(_bold("─" * 60) + "\n")
        return lines


class JsonReporter:
    """Machine-readable JSON output."""

    def report(self, project: ProjectResult) -> str:
        out = {
            "root": project.root,
            "stats": project.stats(),
            "files": [],
        }
        for fr in project.files:
            file_data: dict = {
                "filepath": fr.filepath,
                "module": fr.module_name,
            }
            if fr.parse_error:
                file_data["parse_error"] = fr.parse_error
            else:
                seen = set()
                bindings = []
                for qname, sym in fr.result.bindings:
                    if qname in seen:
                        continue
                    seen.add(qname)
                    bindings.append({
                        "name": qname,
                        "type": str(sym.inferred_type),
                        "line": sym.defined_at[1] if sym.defined_at else None,
                    })
                file_data["bindings"] = bindings
                file_data["function_returns"] = {
                    k: str(v) for k, v in fr.result.function_returns.items()
                }
                file_data["class_attrs"] = {
                    k: str(v) for k, v in fr.result.class_attrs.items()
                }
            out["files"].append(file_data)
        return json.dumps(out, indent=2)
