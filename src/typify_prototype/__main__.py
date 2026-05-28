import hashlib
import json
import argparse
import sys
import zipfile
from pathlib import Path

import gdown
from rich.progress import Progress, SpinnerColumn, TextColumn, track

from .pipeline import collect_entries
from .usage.symbol_table import Registry
from .usage.collector import collect
from .usage.infer import infer_file
from .usage.callsite import apply_callsites, infer_callsite_returns
from .retrieval.build import build_index
from .retrieval.query import TypeRetriever
from .retrieval.retrieve_file import retrieve_file
from .type4py.infer_file import infer_file as type4py_infer_file

_DEFAULT_CONFIG = {
    "context-retrieval": True,
    "context-index-download": "https://drive.google.com/file/d/1rzxFqKOo-A4mlctp6bzekky_80EIS-Xa/view?usp=sharing",
    "retrieval-top-k": 5,
    "type4py": True,
    "type4py-api-url": "https://type4py.ali-aman.ca/api/predict?tc=0",
    "augment-context": False,
    "propagation-passes": 3,
    "symbolic-depth": 3,
}


def _maybe_download_index(output_dir: Path, config: dict) -> None:
    """Download and extract the context index if retrieval is on and index is absent."""
    if not config.get("context-retrieval", _DEFAULT_CONFIG["context-retrieval"]):
        return
    index_dir = output_dir / "context-index"
    if index_dir.is_dir():
        return
    url = config.get("context-index-download", _DEFAULT_CONFIG["context-index-download"])
    if not url:
        return

    zip_path = output_dir / "context-index.zip"
    with Progress(SpinnerColumn(), TextColumn("{task.description}"), transient=False) as progress:
        task = progress.add_task("Downloading context index...", total=None)
        gdown.download(url=url, output=str(zip_path), quiet=True)
        progress.update(task, description="Extracting context index...  ")
        with zipfile.ZipFile(zip_path, "r") as zf:
            index_dir.mkdir(parents=True, exist_ok=True)
            zf.extractall(index_dir)
        progress.update(task, description="Context index ready.         ")
    zip_path.unlink(missing_ok=True)


def _load_changed(path: Path) -> dict:
    if path.exists():
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    return {}


def _compute_changed(
    pairs: list[tuple[Path, str]],
    prev_retrieval: dict,
    prev_type4py: dict,
    use_retrieval: bool,
    use_type4py: bool,
) -> tuple[set[str], set[str], dict[str, dict]]:
    """Return (retrieval_changed, type4py_changed, new_sigs), hashing each file at most once."""
    retrieval_changed: set[str] = set()
    type4py_changed: set[str] = set()
    new_sigs: dict[str, dict] = {}
    for py_path, relpath in pairs:
        size = py_path.stat().st_size
        sha: str | None = None

        r_changed = False
        if use_retrieval:
            old = prev_retrieval.get(relpath)
            if old is None or size != old["size"]:
                r_changed = True
            else:
                sha = hashlib.sha256(py_path.read_bytes()).hexdigest()
                r_changed = sha != old["sha256"]

        t_changed = False
        if use_type4py:
            old = prev_type4py.get(relpath)
            if old is None or size != old["size"]:
                t_changed = True
            else:
                if sha is None:
                    sha = hashlib.sha256(py_path.read_bytes()).hexdigest()
                t_changed = sha != old["sha256"]

        if r_changed or t_changed:
            if sha is None:
                sha = hashlib.sha256(py_path.read_bytes()).hexdigest()
            new_sigs[relpath] = {"size": size, "sha256": sha}
            if r_changed:
                retrieval_changed.add(relpath)
            if t_changed:
                type4py_changed.add(relpath)

    return retrieval_changed, type4py_changed, new_sigs


def _save_changed(
    path: Path,
    pairs: list[tuple[Path, str]],
    prev: dict,
    new_sigs: dict,
    pass_changed: set[str],
) -> None:
    updated = {
        relpath: new_sigs[relpath] if relpath in pass_changed else prev[relpath]
        for _, relpath in pairs
    }
    path.write_text(json.dumps(updated, indent="\t", ensure_ascii=False), encoding="utf-8")


def _read_inference_snapshot(path: Path) -> dict:
    """Extract non-empty retrieved/type4py fields from an existing entry JSON."""
    old = json.loads(path.read_text(encoding="utf-8"))
    snap: dict[str, dict] = {}
    for key, entry in old.items():
        entry_snap: dict = {}
        if "type" in entry:
            if entry["type"].get("retrieved") or entry["type"].get("type4py"):
                entry_snap["retrieved"] = entry["type"]["retrieved"]
                entry_snap["type4py"] = entry["type"]["type4py"]
        if "params" in entry:
            params_snap: dict[str, dict] = {}
            for p, pdata in entry["params"].items():
                if pdata.get("retrieved") or pdata.get("type4py"):
                    params_snap[p] = {
                        "retrieved": pdata["retrieved"],
                        "type4py": pdata["type4py"],
                    }
            if params_snap:
                entry_snap["params"] = params_snap
        if entry_snap:
            snap[key] = entry_snap
    return snap


def _apply_snapshot(
    entries: dict,
    snap: dict,
    restore_retrieved: bool,
    restore_type4py: bool,
) -> None:
    """Merge snapshotted retrieved/type4py fields back into in-memory entries."""
    for key, entry_snap in snap.items():
        entry = entries.get(key)
        if entry is None:
            continue
        if "type" in entry:
            if restore_retrieved and "retrieved" in entry_snap:
                entry["type"]["retrieved"] = entry_snap["retrieved"]
            if restore_type4py and "type4py" in entry_snap:
                entry["type"]["type4py"] = entry_snap["type4py"]
        if "params" in entry and "params" in entry_snap:
            for p, psnap in entry_snap["params"].items():
                if p in entry["params"]:
                    if restore_retrieved and "retrieved" in psnap:
                        entry["params"][p]["retrieved"] = psnap["retrieved"]
                    if restore_type4py and "type4py" in psnap:
                        entry["params"][p]["type4py"] = psnap["type4py"]


def _load_config(output_dir: Path) -> dict:
    config_path = output_dir / "config.json"
    if config_path.exists():
        with config_path.open(encoding="utf-8") as f:
            return json.load(f)
    config_path.write_text(
        json.dumps(_DEFAULT_CONFIG, indent="\t", ensure_ascii=False), encoding="utf-8"
    )
    return dict(_DEFAULT_CONFIG)


def _cmd_infer(args: argparse.Namespace) -> None:
    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()

    if not input_dir.is_dir():
        sys.exit(f"Error: '{input_dir}' is not a directory.")

    py_files = sorted(input_dir.glob("**/*.py"))
    if not py_files:
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    types_dir = output_dir / "types"
    types_dir.mkdir(exist_ok=True)

    config = _load_config(output_dir)
    top_k: int = config.get("retrieval-top-k", _DEFAULT_CONFIG["retrieval-top-k"])

    _maybe_download_index(output_dir, config)

    pairs: list[tuple[Path, str]] = [
        (p, str(p.relative_to(input_dir))) for p in py_files
    ]
    pad = len(str(len(py_files) - 1))

    use_retrieval = config.get("context-retrieval", _DEFAULT_CONFIG["context-retrieval"])
    use_type4py = config.get("type4py", _DEFAULT_CONFIG["type4py"])

    # Before pass 1 wipes existing JSONs, snapshot retrieved/type4py data for files
    # that won't be reprocessed by passes 4/5 so we can restore it afterwards.
    prev_retrieval: dict = {}
    prev_type4py: dict = {}
    retrieval_changed: set[str] = set()
    type4py_changed: set[str] = set()
    new_sigs: dict[str, dict] = {}
    old_inference: dict[str, dict] = {}   # relpath -> snapshot
    restore_retrieved_for: set[str] = set()
    restore_type4py_for: set[str] = set()

    if use_retrieval or use_type4py:
        prev_retrieval = _load_changed(output_dir / "retrieval-changed.json")
        prev_type4py = _load_changed(output_dir / "type4py-changed.json")
        retrieval_changed, type4py_changed, new_sigs = _compute_changed(
            pairs, prev_retrieval, prev_type4py, use_retrieval, use_type4py
        )
        all_relpaths = {r for _, r in pairs}
        restore_retrieved_for = (all_relpaths - retrieval_changed) if use_retrieval else all_relpaths
        restore_type4py_for = (all_relpaths - type4py_changed) if use_type4py else all_relpaths
        needs_snapshot = restore_retrieved_for | restore_type4py_for

        old_index_path = output_dir / "index.json"
        if old_index_path.exists() and needs_snapshot:
            old_index = json.loads(old_index_path.read_text(encoding="utf-8"))
            for relpath in needs_snapshot:
                old_rel = old_index.get(relpath)
                if old_rel:
                    old_json_path = output_dir / old_rel
                    if old_json_path.exists():
                        snap = _read_inference_snapshot(old_json_path)
                        if snap:
                            old_inference[relpath] = snap

    # Pass 1: collect skeleton entries and write initial JSONs immediately
    all_entries: dict[str, dict[str, dict]] = {}
    out_paths: dict[str, Path] = {}
    index: dict[str, str] = {}
    for i, (py_path, relpath) in enumerate(pairs):
        try:
            entries = collect_entries(py_path)
        except (SyntaxError, Exception):
            entries = {}
        all_entries[relpath] = entries
        out_name = f"{i:0{pad}}.json"
        out_path = types_dir / out_name
        out_paths[relpath] = out_path
        out_path.write_text(
            json.dumps(entries, indent="\t", ensure_ascii=False), encoding="utf-8"
        )
        index[relpath] = f"types/{out_name}"

    (output_dir / "index.json").write_text(
        json.dumps(index, indent="\t", ensure_ascii=False), encoding="utf-8"
    )

    # Remove types JSONs for source files deleted since the last run
    referenced_names = {Path(v).name for v in index.values()}
    for stale in types_dir.glob("*.json"):
        if stale.name not in referenced_names:
            stale.unlink()

    # Pass 2: build project-wide registry (classes, functions, field types)
    registry = Registry()
    collect([(p, r) for p, r in pairs], registry)

    # Pass 3: usage-driven inference
    for py_path, relpath in track(pairs, description="Usage inference    "):
        infer_file(py_path, relpath, registry, all_entries[relpath])

    # Propagation passes: each iteration resolves one more level of depth in the call chain.
    # Iteration i applies callsites from the previous infer pass, then re-infers so that
    # newly-typed params propagate to their callees in the next iteration.
    prop_passes = config.get("propagation-passes", _DEFAULT_CONFIG["propagation-passes"])
    for _ in range(prop_passes):
        apply_callsites(registry, all_entries)
        registry.callsite_records.clear()
        for py_path, relpath in pairs:
            infer_file(py_path, relpath, registry, all_entries[relpath], record_callsites=True)

    # Final callsite aggregation to capture types from the last propagation pass
    apply_callsites(registry, all_entries)

    # Pass 3b.5: per-callsite return type inference (with optional symbolic recursion)
    sym_depth: int = config.get("symbolic-depth", _DEFAULT_CONFIG["symbolic-depth"])
    py_path_map = {relpath: py_path for py_path, relpath in pairs}
    infer_callsite_returns(py_path_map, registry, all_entries, sym_depth=sym_depth)

    # Final body propagation: re-infer with all callsite-derived types and write outputs
    for py_path, relpath in track(pairs, description="Body propagation   "):
        infer_file(py_path, relpath, registry, all_entries[relpath], record_callsites=False)
        out_paths[relpath].write_text(
            json.dumps(all_entries[relpath], indent="\t", ensure_ascii=False),
            encoding="utf-8",
        )

    # Restore retrieved/type4py results for files that won't be reprocessed by passes 4/5
    for relpath, snap in old_inference.items():
        _apply_snapshot(
            all_entries[relpath],
            snap,
            relpath in restore_retrieved_for,
            relpath in restore_type4py_for,
        )
        out_paths[relpath].write_text(
            json.dumps(all_entries[relpath], indent="\t", ensure_ascii=False),
            encoding="utf-8",
        )

    if use_retrieval or use_type4py:
        # Pass 4: retrieval-driven inference (skipped if index is absent or disabled)
        index_dir = output_dir / "context-index"
        retrieval_pairs = [(p, r) for p, r in pairs if r in retrieval_changed]
        if use_retrieval and index_dir.is_dir() and retrieval_pairs:
            retriever = TypeRetriever(index_dir)
            for py_path, relpath in track(retrieval_pairs, description="Retrieval inference"):
                retrieve_file(py_path, relpath, retriever, all_entries[relpath], top_k)
                out_paths[relpath].write_text(
                    json.dumps(all_entries[relpath], indent="\t", ensure_ascii=False),
                    encoding="utf-8",
                )
            _save_changed(output_dir / "retrieval-changed.json", pairs, prev_retrieval, new_sigs, retrieval_changed)

        # Pass 5: Type4Py inference (skipped if disabled in config)
        type4py_pairs = [(p, r) for p, r in pairs if r in type4py_changed]
        if use_type4py and type4py_pairs:
            api_url = config.get("type4py-api-url", _DEFAULT_CONFIG["type4py-api-url"])
            for py_path, relpath in track(type4py_pairs, description="Type4Py inference  "):
                type4py_infer_file(py_path, relpath, all_entries[relpath], api_url)
                out_paths[relpath].write_text(
                    json.dumps(all_entries[relpath], indent="\t", ensure_ascii=False),
                    encoding="utf-8",
                )
            _save_changed(output_dir / "type4py-changed.json", pairs, prev_type4py, new_sigs, type4py_changed)


def _cmd_build(args: argparse.Namespace) -> None:
    build_index(
        dataset_root=args.dataset_root.resolve(),
        index_dir=args.index.resolve(),
        workers=args.workers,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    infer_parser = subparsers.add_parser("infer")
    infer_parser.add_argument("input_dir", type=Path)
    infer_parser.add_argument("output_dir", type=Path)

    build_parser = subparsers.add_parser("build", help="Build Tantivy index from a dataset")
    build_parser.add_argument("dataset_root", type=Path)
    build_parser.add_argument("index", type=Path)
    build_parser.add_argument("--workers", type=int, default=4)

    args = parser.parse_args()
    if args.command == "infer":
        _cmd_infer(args)
    elif args.command == "build":
        _cmd_build(args)


if __name__ == "__main__":
    main()
