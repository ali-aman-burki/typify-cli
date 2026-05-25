import subprocess
import sys
import json

from pathlib import Path
from typing import Union

from typify_prototype.preprocessing.dependency_utils import GraphBuilder
from typify_prototype.preprocessing.core import GlobalContext
from typify_prototype.preprocessing.library_meta import LibraryMeta


class Preloader:

    @staticmethod
    def _extract_current_env(python_executable=sys.executable) -> dict[str, Union[Path, list[Path]]]:
        script = """
import site, json

info = {
    "user_site_lib": site.getusersitepackages(),
    "site_libs": site.getsitepackages(),
}

print(json.dumps(info))
"""
        result = subprocess.run(
            [python_executable, "-c", script],
            capture_output=True,
            text=True,
            check=True
        )
        raw_info = json.loads(result.stdout)
        return {
            "user_site_lib": Path(raw_info["user_site_lib"]),
            "site_libs": [Path(p) for p in raw_info["site_libs"]],
        }

    @staticmethod
    def load(
        config: dict[str, Union[str, list[str], dict[str, str]]],
        project_dir: Path
    ):
        paths = [project_dir]
        inference: dict[str, Path] = {}

        cenv = Preloader._extract_current_env()
        raw_paths = config.get("paths", [])

        for p in raw_paths:
            if p == "{auto}":
                for site in cenv.values():
                    if isinstance(site, Path):
                        paths.append(site)
                    elif isinstance(site, list):
                        paths.extend([s for s in site if isinstance(s, Path)])
            else:
                try:
                    paths.append(Path(p).resolve())
                except Exception:
                    continue

        for k, v in config.get("inference", {}).items():
            try:
                inference[k] = Path(v)
            except Exception:
                continue

        inference = {k: Path(v.resolve().as_posix()) for k, v in inference.items()}
        paths = [Path(p.resolve().as_posix()) for p in paths]

        GlobalContext.libs.clear()
        for path in paths:
            lib = LibraryMeta(path)
            lib.build()
            GlobalContext.libs[path] = lib

        GlobalContext.path_index.clear()
        for lib in GlobalContext.libs.values():
            for apath, meta in lib.path_index.items():
                GlobalContext.path_index[apath.resolve()] = meta

        for k, v in inference.items():
            GlobalContext.inference[k] = GlobalContext.path_index.get(v.resolve())

        GraphBuilder.build_graph_all()
