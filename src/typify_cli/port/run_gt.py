import ast
import json
import warnings

from pathlib import Path
from tqdm import tqdm

class TypeAnnotationExtractor(ast.NodeVisitor):
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.results = []
        self.scope_stack = []

    def current_scope(self):
        return ".".join(self.scope_stack)

    def visit_ClassDef(self, node: ast.ClassDef):
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self.scope_stack.append(node.name)

        for arg in node.args.args + node.args.kwonlyargs:
            if arg.annotation is not None:
                self.results.append({
                    "category": "argument",
                    "scope": self.current_scope(),
                    "name": arg.arg,
                    "type": [ast.unparse(arg.annotation)],
                    "locations": [[node.lineno, node.col_offset]]
                })

        if node.returns is not None:
            self.results.append({
                "category": "return",
                "scope": self.current_scope(),
                "name": node.name,
                "type": [ast.unparse(node.returns)],
                "locations": [[node.lineno, node.col_offset]]
            })

        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self.visit_FunctionDef(node)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        if node.annotation is not None:
            target_name = None

            if isinstance(node.target, ast.Name):
                target_name = node.target.id
            elif isinstance(node.target, ast.Attribute):
                target_name = ast.unparse(node.target)

            if target_name:
                self.results.append({
                    "category": "variable",
                    "scope": self.current_scope(),
                    "name": target_name,
                    "type": [ast.unparse(node.annotation)],
                    "locations": [[node.lineno, node.col_offset]]
                })

        self.generic_visit(node)


def merge_annotation_buckets(buckets):
    merged = {}

    for b in buckets:
        key = (b["category"], b["scope"], b["name"])
        if key not in merged:
            merged[key] = {
                "category": b["category"],
                "scope": b["scope"],
                "name": b["name"],
                "type": set(b["type"]),
                "locations": list(b["locations"]),
            }
        else:
            merged[key]["type"].update(b["type"])
            merged[key]["locations"].extend(b["locations"])

    finalized = []
    for v in merged.values():
        types = sorted(v["type"])
        if len(types) > 1:
            v["type"] = [f"Union[{', '.join(types)}]"]
        else:
            v["type"] = [types[0]]

        v["locations"] = [list(x) for x in {tuple(l) for l in v["locations"]}]
        finalized.append(v)

    return finalized

def extract_type_annotations(
    projects_root: str,
    output_json_path: str,
    merge_buckets: bool = False,
    paths_txt: str = None,
):
    warnings.filterwarnings("ignore")

    root = Path(projects_root).resolve()
    output_path = Path(output_json_path).resolve()

    big_dict = {}

    def process_file(py_file: Path, key: str):
        try:
            source = py_file.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(source)

            extractor = TypeAnnotationExtractor(py_file)
            extractor.visit(tree)

            if extractor.results:
                buckets = extractor.results
                if merge_buckets:
                    buckets = merge_annotation_buckets(buckets)
                big_dict[key] = buckets
        except Exception:
            return

    if paths_txt is not None:
        txt_path = Path(paths_txt).resolve()
        rel_paths: list[str] = []

        for line in txt_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            rel_paths.append(s.replace("\\", "/"))

        for rel_str in tqdm(
            rel_paths,
            total=len(rel_paths),
            desc="Building Groundtruth",
            ascii=(" ", "━"),
            bar_format="{desc}: [{bar:50}] {n_fmt}/{total_fmt}",
        ):
            py_file = (root / rel_str).resolve()

            if py_file.is_file() and py_file.suffix == ".py":
                process_file(py_file, py_file.resolve().as_posix())

        sorted_big_dict = dict(sorted(big_dict.items(), key=lambda x: x[0]))
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(sorted_big_dict, f, indent="\t", ensure_ascii=False)
        return

    repos = [p for p in root.glob("*/*") if p.is_dir()]

    for repo_path in tqdm(
        repos,
        desc="Building Groundtruth",
        ascii=(" ", "━"),
        bar_format="{desc}: [{bar:50}] {n_fmt}/{total_fmt}",
    ):
        for py_file in repo_path.rglob("*.py"):
            if not py_file.is_file():
                continue

            process_file(py_file, str(py_file.resolve().as_posix()))

    sorted_big_dict = dict(sorted(big_dict.items(), key=lambda x: x[0]))

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(sorted_big_dict, f, indent="\t", ensure_ascii=False)
