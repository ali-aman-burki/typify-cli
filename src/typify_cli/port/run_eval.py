import json
from collections import defaultdict

from rich.console import Console
from rich.table import Table

from .preprocessing.typeexpr import (
    parse_typeexpr,
    exact_match,
    base_match,
    classify_kind,
)

def eval(gt_path: str, tool_path: str, topn: int) -> None:
    """
    Compare ground-truth bucket types against tool predictions using typeexpr.py.
    Prints summary statistics and clean terminal tables.
    """

    console = Console()

    with open(gt_path, "r") as f:
        gt_data = json.load(f)
    with open(tool_path, "r") as f:
        tool_data = json.load(f)

    total_buckets = 0
    exact_matches = 0
    base_matches = 0

    # Aggregations
    by_category = defaultdict(lambda: {"exact": 0, "base": 0, "none": 0, "total": 0})
    by_kind = defaultdict(lambda: {"exact": 0, "base": 0, "none": 0, "total": 0})

    shared_paths = set(gt_data.keys()) & set(tool_data.keys())

    # -----------------------------
    # Main evaluation loop
    # -----------------------------
    for filepath in shared_paths:
        gt_buckets = gt_data[filepath]
        tool_buckets = tool_data[filepath]

        # Build lookup for tool buckets
        tool_index = {
            (b["name"], b["scope"], b["category"]): b
            for b in tool_buckets
        }

        for gt_bucket in gt_buckets:
            total_buckets += 1

            name = gt_bucket["name"]
            scope = gt_bucket["scope"]
            category = gt_bucket["category"]

            key = (name, scope, category)
            tool_bucket = tool_index.get(key)

            gt_type_raw = gt_bucket["type"][0]
            gt_type = parse_typeexpr(gt_type_raw)

            if tool_bucket is None:
                result = "none"

                by_category[category]["total"] += 1
                by_category[category][result] += 1

                gt_kind = classify_kind(gt_type)
                by_kind[gt_kind]["total"] += 1
                by_kind[gt_kind][result] += 1
                continue

            tool_types_raw = tool_bucket["type"]
            top_tool_types = tool_types_raw[:topn]

            found_exact = False
            found_base = False

            for pred_raw in top_tool_types:
                pred_type = parse_typeexpr(pred_raw)

                if exact_match(gt_type, pred_type):
                    found_exact = True
                    found_base = True
                    break
                elif base_match(gt_type, pred_type):
                    found_base = True

            if found_exact:
                exact_matches += 1
                base_matches += 1
                result = "exact"
            elif found_base:
                base_matches += 1
                result = "base"
            else:
                result = "none"

            by_category[category]["total"] += 1
            by_category[category][result] += 1

            gt_kind = classify_kind(gt_type)
            by_kind[gt_kind]["total"] += 1
            by_kind[gt_kind][result] += 1

    exact_pct = (exact_matches / total_buckets * 100) if total_buckets else 0.0
    base_pct = (base_matches / total_buckets * 100) if total_buckets else 0.0

    print("====== Prediction Evaluation Results =====")
    print(f"Top-N setting: {topn}")
    print(f"Total buckets evaluated: {total_buckets}")
    print()
    print(f"Exact matches: {exact_matches} ({exact_pct:.2f}%)")
    print(f"Base matches:  {base_matches} ({base_pct:.2f}%)")
    print("==========================================")

    print()
    _print_summary_table(
        title="Results",
        data=by_category,
        console=console,
    )

def _print_summary_table(
    title: str,
    data: dict[str, dict[str, int]],
    console: Console,
) -> None:
    table = Table(title=title, show_lines=True)

    table.add_column("Group", style="cyan", no_wrap=True)
    table.add_column("Exact %", justify="right", style="green")
    table.add_column("Base %", justify="right", style="yellow")

    total_exact = 0
    total_base_only = 0
    total_count = 0

    for key, stats in sorted(data.items()):
        total = stats["total"]
        exact = stats["exact"]
        base_only = stats["base"]

        total_exact += exact
        total_base_only += base_only
        total_count += total

        exact_pct = (exact / total * 100) if total else 0.0
        base_pct = ((exact + base_only) / total * 100) if total else 0.0

        table.add_row(
            str(key),
            f"{exact_pct:.2f}%",
            f"{base_pct:.2f}%",
        )

    if total_count:
        total_exact_pct = total_exact / total_count * 100
        total_base_pct = (total_exact + total_base_only) / total_count * 100
    else:
        total_exact_pct = total_base_pct = 0.0

    table.add_row(
        "TOTAL",
        f"{total_exact_pct:.2f}%",
        f"{total_base_pct:.2f}%",
        style="bold",
    )

    console.print(table)
