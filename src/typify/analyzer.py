"""
Project-level analyzer: walks a directory, runs per-file inference,
and aggregates results.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .engine import InferenceResult, TypeInferenceVisitor
from .scope import Symbol
from .types import InferredType, UNKNOWN


@dataclass
class FileResult:
    filepath: str
    module_name: str
    result: InferenceResult
    parse_error: Optional[str] = None


@dataclass
class ProjectResult:
    root: str
    files: List[FileResult] = field(default_factory=list)

    # Aggregated views
    @property
    def all_bindings(self) -> List[Tuple[str, str, Symbol]]:
        """Returns (module, qualified_name, symbol) for every binding."""
        out = []
        for fr in self.files:
            if fr.parse_error:
                continue
            seen = set()
            for qname, sym in fr.result.bindings:
                key = (fr.module_name, qname)
                if key not in seen:
                    seen.add(key)
                    out.append((fr.module_name, qname, sym))
        return out

    @property
    def function_returns(self) -> List[Tuple[str, str, InferredType]]:
        """Returns (module, func_name, return_type) for all functions."""
        out = []
        for fr in self.files:
            if fr.parse_error:
                continue
            for fname, rtype in fr.result.function_returns.items():
                out.append((fr.module_name, fname, rtype))
        return out

    @property
    def class_attrs(self) -> List[Tuple[str, str, InferredType]]:
        """Returns (module, attr_key, type) for all class attributes."""
        out = []
        for fr in self.files:
            if fr.parse_error:
                continue
            for key, t in fr.result.class_attrs.items():
                out.append((fr.module_name, key, t))
        return out

    def stats(self) -> Dict[str, int]:
        total_bindings = 0
        inferred = 0
        unknown = 0
        for _m, _n, sym in self.all_bindings:
            total_bindings += 1
            if sym.inferred_type.is_unknown():
                unknown += 1
            else:
                inferred += 1
        return {
            "files": len(self.files),
            "parse_errors": sum(1 for f in self.files if f.parse_error),
            "total_bindings": total_bindings,
            "inferred": inferred,
            "unknown": unknown,
            "coverage_pct": round(inferred / total_bindings * 100, 1) if total_bindings else 0,
        }


class ProjectAnalyzer:
    """
    Walks a Python project directory and runs type inference on each .py file.
    """

    def __init__(self, root: str) -> None:
        self.root = os.path.abspath(root)

    def analyze(self) -> ProjectResult:
        project = ProjectResult(root=self.root)

        py_files = sorted(Path(self.root).rglob("*.py"))
        for path in py_files:
            module_name = self._module_name(path)
            fr = self._analyze_file(str(path), module_name)
            project.files.append(fr)

        return project

    def _module_name(self, path: Path) -> str:
        try:
            rel = path.relative_to(self.root)
        except ValueError:
            return path.stem
        parts = list(rel.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        return ".".join(parts) if parts else path.stem

    def _analyze_file(self, filepath: str, module_name: str) -> FileResult:
        try:
            source = Path(filepath).read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return FileResult(filepath=filepath, module_name=module_name,
                              result=InferenceResult(filepath),
                              parse_error=f"IOError: {e}")
        try:
            visitor = TypeInferenceVisitor(filepath, module_name)
            result = visitor.infer(source)
            return FileResult(filepath=filepath, module_name=module_name, result=result)
        except SyntaxError as e:
            return FileResult(filepath=filepath, module_name=module_name,
                              result=InferenceResult(filepath),
                              parse_error=f"SyntaxError: {e}")
        except Exception as e:
            return FileResult(filepath=filepath, module_name=module_name,
                              result=InferenceResult(filepath),
                              parse_error=f"Error: {e}")
