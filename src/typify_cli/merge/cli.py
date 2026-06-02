import sys
import click

from pathlib import Path

from . import (
    run_infer,
    run_build,
    run_gt,
    run_eval,
    stubs_dir
)

sys.setrecursionlimit(5000)

@click.group()
@click.version_option("0.1.0", prog_name="Typify")
def cli():
    """Typify: Static Type Inference Tool"""
    pass


COMMON_INFER_OPTIONS = [
    click.option("--output-types", type=click.Path(), help="File to output inferred types as JSON."),
    click.option("--output-log", type=click.Path(), help="File to output inference log."),
    click.option(
        "--log-level",
        default="off",
        show_default=True,
        type=click.Choice(["off", "info", "debug", "trace", "error", "warning"]),
        help="Verbosity of logging output."
    ),
    click.option("--clear-cache", is_flag=True, help="Clear the cache before running."),
    click.option("--prune-cache", is_flag=True, help="Remove invalid cache entries."),
    click.option("--cache", is_flag=True, help="Cache usage during inference."),
    click.option("--heur", is_flag=True, help="Enable heuristic-based inference."),
    click.option("--usage", is_flag=True, help="Enable usage-driven inference."),
    click.option("--topn", default=1, show_default=True, help="Number of top inference candidates to output."),
    click.option(
        "--cache-dir",
        default="{auto}",
        show_default=True,
        type=click.Path(),
        help="Path to cache directory. Defaults to system cache."
    ),
    click.option(
        "--paths",
        multiple=True,
        default=(f"{stubs_dir}/stdlib/",),
        show_default=True,
        help="Additional search paths."
    )
]


def apply_common_options(func):
    for opt in reversed(COMMON_INFER_OPTIONS):
        func = opt(func)
    return func


@cli.command("project")
@click.argument("project_dir", type=click.Path(exists=True))
@apply_common_options
def project(**kwargs):
    """Run inference on a Python project."""
    run_infer.infer_project(**kwargs)


@cli.command("repo")
@click.argument("repo_dir", type=click.Path(exists=True))
@click.option(
    "--utime",
    default=80,
    show_default=True,
    help="Maximum inference time (seconds) per project."
)
@apply_common_options
def repo(**kwargs):
    """Run inference on a Python repository."""
    run_infer.infer_repo(**kwargs)

@cli.command("dataset")
@click.argument("dataset_dir", type=click.Path(exists=True))
@click.option(
    "--utime",
    default=80,
    show_default=True,
    help="Maximum inference time (seconds) per project."
)
@apply_common_options
def dataset(**kwargs):
    """Run inference on a dataset of repositories (author/repo structure)."""
    run_infer.infer_dataset(**kwargs)

@cli.command("gt")
@click.argument("dataset", type=click.Path(exists=True))
@click.option("--output-types", type=click.Path(), help="Path to output JSON file with extracted type annotations.")
@click.option(
    "--paths-txt",
    type=click.Path(exists=True),
    default=None,
    help=(
        "Text file with one relative path per line (relative to DATASET dir). "
        "If provided, overrides directory scanning."
    ),
)
def gt(dataset, output_types, paths_txt):
    """Extract ground truth type annotations from a dataset of repositories."""
    run_gt.extract_type_annotations(
        projects_root=dataset,
        output_json_path=output_types,
        merge_buckets=True,
        paths_txt=paths_txt,
    )

@cli.command("build")
@click.option("--train-files", required=True, type=click.Path(exists=True))
@click.option("--output-dir", default="typify/index", show_default=True)
@click.option("--max-features", default=20000, show_default=True, help="Maximum features for TF-IDF vectorizer.")
@click.option("--ngram", nargs=2, type=int, default=(1, 2), show_default=True, help="n-gram range for TF-IDF.")
@click.option("--min-df", default=1, show_default=True, help="Minimum document frequency for TF-IDF terms.")
def build(train_files, output_dir, max_features, ngram, min_df):
    """Build a context index from annotated Python files."""
    run_build.build_index(
        train_list_file=train_files,
        output_dir=output_dir,
        max_features=max_features,
        ngram_range=tuple(ngram),
        min_df=min_df,
    )

@cli.command("eval")
@click.argument("gt_path", type=click.Path(exists=True))
@click.argument("tool_path", type=click.Path(exists=True))
@click.option("--topn", default=1, show_default=True, help="Evaluate based on Top N predictions.")
def eval(gt_path, tool_path, topn):
	"""Evaluate tool predictions against ground-truth types."""
	run_eval.eval(gt_path, tool_path, topn)

def main():
    cli()


if __name__ == "__main__":
    main()
