"""
Walks a ManyTypes4Py-style dataset root and builds a Tantivy index
of all annotation sites extracted from .py files.

Dataset layout expected:
    dataset_root/
        author1/
            repo1/
                **/*.py
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import tantivy
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn, MofNCompleteColumn, Progress, SpinnerColumn,
    TextColumn, TimeElapsedColumn, TimeRemainingColumn,
)

from .features import AnnotationSite, extract_from_file

logger = logging.getLogger(__name__)


def build_schema() -> tantivy.Schema:
    builder = tantivy.SchemaBuilder()
    builder.add_text_field("kind",            stored=True)
    builder.add_text_field("identifier",      stored=True)
    builder.add_text_field("function_name",   stored=True)
    builder.add_text_field("class_name",      stored=True)
    builder.add_text_field("decorators",      stored=True)
    builder.add_text_field("default_kind",    stored=True)
    builder.add_text_field("fn_flags",        stored=True)
    builder.add_text_field("sibling_names",   stored=True)
    builder.add_text_field("sibling_types",   stored=True)
    builder.add_text_field("attributes",      stored=True)
    builder.add_text_field("usage_flags",     stored=True)
    builder.add_text_field("annotated_type",  stored=True)
    builder.add_text_field("source_file",     stored=True, tokenizer_name="raw")
    builder.add_integer_field("line",         stored=True)
    return builder.build()


def _site_to_doc(site: AnnotationSite, schema: tantivy.Schema) -> tantivy.Document:
    usage_flags: list[str] = []
    if site.is_iterated:      usage_flags.append("iterated")
    if site.is_indexed:       usage_flags.append("indexed")
    if site.is_called:        usage_flags.append("called")
    if site.is_none_compared: usage_flags.append("none_compared")

    return tantivy.Document(
        kind=site.kind,
        identifier=site.identifier,
        function_name=site.function_name or "",
        class_name=site.class_name or "",
        decorators=" ".join(site.decorators),
        default_kind=site.default_value_kind or "",
        fn_flags=" ".join(site.function_name_flags),
        sibling_names=" ".join(n for n, _ in site.sibling_params),
        sibling_types=" ".join(t for _, t in site.sibling_params if t),
        attributes=" ".join(site.attribute_accesses),
        usage_flags=" ".join(usage_flags),
        annotated_type=site.annotated_type,
        source_file=site.source_file,
        line=site.line,
    )


def _collect_py_files(dataset_root: Path) -> list[Path]:
    py_files = []
    for root, _dirs, files in os.walk(dataset_root):
        for fname in files:
            if fname.endswith(".py"):
                py_files.append(Path(root) / fname)
    return py_files


def _process_file(path_str: str) -> list[dict]:
    return [dataclasses.asdict(s) for s in extract_from_file(path_str)]


def build_index(dataset_root: Path, index_dir: Path, workers: int = 4) -> None:
    console = Console()
    index_dir.mkdir(parents=True, exist_ok=True)

    schema = build_schema()
    index = tantivy.Index(schema, path=str(index_dir))
    writer = index.writer(heap_size=256 * 1024 * 1024)

    with console.status("[bold cyan]Scanning for .py files…", spinner="dots"):
        py_files = _collect_py_files(dataset_root)

    console.print(
        f"[bold green]Found[/bold green] [bold]{len(py_files):,}[/bold] "
        f".py files in [cyan]{dataset_root}[/cyan]"
    )

    total_sites  = 0
    total_files  = 0
    failed_files = 0
    t0 = time.time()

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=40),
        MofNCompleteColumn(),
        TextColumn("•"),
        TimeElapsedColumn(),
        TextColumn("•"),
        TimeRemainingColumn(),
        TextColumn("• [green]{task.fields[sites]:,} sites[/green]"),
        TextColumn("• [red]{task.fields[failed]} failed[/red]"),
        console=console,
        refresh_per_second=10,
    )

    with progress:
        task = progress.add_task("Indexing", total=len(py_files), sites=0, failed=0)

        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_process_file, str(p)): p for p in py_files}

            for future in as_completed(futures):
                try:
                    site_dicts = future.result()
                except Exception as exc:
                    logger.debug("Worker error on %s: %s", futures[future], exc)
                    failed_files += 1
                else:
                    for sd in site_dicts:
                        writer.add_document(_site_to_doc(AnnotationSite(**sd), schema))
                        total_sites += 1
                    total_files += 1

                progress.update(task, advance=1, sites=total_sites, failed=failed_files)

    elapsed = time.time() - t0

    with console.status("[bold yellow]Committing index…", spinner="dots"):
        writer.commit()
    with console.status("[bold yellow]Optimising index…", spinner="dots"):
        writer.wait_merging_threads()

    console.print(Panel(
        f"[bold green]Done![/bold green]\n\n"
        f"  Files processed : [bold]{total_files:,}[/bold]\n"
        f"  Files failed    : [bold red]{failed_files:,}[/bold red]\n"
        f"  Annotation sites: [bold]{total_sites:,}[/bold]\n"
        f"  Elapsed         : [bold]{elapsed:.1f}s[/bold]\n"
        f"  Index location  : [cyan]{index_dir}[/cyan]",
        title="[bold]Indexing complete[/bold]",
        expand=False,
    ))

    (index_dir / "index_meta.json").write_text(json.dumps({
        "dataset_root": str(dataset_root),
        "total_files":  total_files,
        "failed_files": failed_files,
        "total_sites":  total_sites,
        "elapsed_s":    round(elapsed, 1),
    }, indent=2))
