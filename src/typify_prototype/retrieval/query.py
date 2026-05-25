"""
Retriever: given context around an unannotated identifier, query the Tantivy
index and return ranked type candidates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import tantivy


@dataclass
class QueryContext:
    """Context around an unannotated identifier — mirrors AnnotationSite."""
    kind: str                                    # "param" | "return" | "variable"
    identifier: str
    function_name: Optional[str] = None
    class_name: Optional[str] = None
    decorators: list[str] = field(default_factory=list)
    default_value_kind: Optional[str] = None
    sibling_params: list[tuple[str, Optional[str]]] = field(default_factory=list)
    param_position: Optional[int] = None
    function_name_flags: list[str] = field(default_factory=list)
    is_iterated: bool = False
    is_indexed: bool = False
    is_called: bool = False
    is_none_compared: bool = False
    attribute_accesses: list[str] = field(default_factory=list)


@dataclass
class TypeCandidate:
    """One ranked type prediction."""
    annotated_type: str
    score: float
    hit_count: int
    source_file: str
    line: int


def _make_schema() -> tantivy.Schema:
    builder = tantivy.SchemaBuilder()
    builder.add_text_field("kind",           stored=True)
    builder.add_text_field("identifier",     stored=True)
    builder.add_text_field("function_name",  stored=True)
    builder.add_text_field("class_name",     stored=True)
    builder.add_text_field("decorators",     stored=True)
    builder.add_text_field("default_kind",   stored=True)
    builder.add_text_field("fn_flags",       stored=True)
    builder.add_text_field("sibling_names",  stored=True)
    builder.add_text_field("sibling_types",  stored=True)
    builder.add_text_field("attributes",     stored=True)
    builder.add_text_field("usage_flags",    stored=True)
    builder.add_text_field("annotated_type", stored=True)
    builder.add_text_field("source_file",    stored=True, tokenizer_name="raw")
    builder.add_integer_field("line",        stored=True)
    return builder.build()


_SEARCH_FIELDS = [
    "kind", "identifier", "function_name", "class_name",
    "decorators", "default_kind", "fn_flags",
    "sibling_names", "sibling_types", "attributes", "usage_flags",
]


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _build_query_str(ctx: QueryContext) -> str:
    parts: list[str] = []

    def add(field: str, value: str, boost: float) -> None:
        v = value.strip()
        if not v:
            return
        parts.append(f'{field}:"{_escape(v)}"^{boost}')

    def add_many(field: str, values: list[str], boost: float) -> None:
        for v in values:
            add(field, v, boost)

    add("kind",        ctx.kind,              3.0)
    add("identifier",  ctx.identifier,        2.0)

    if ctx.default_value_kind:
        add("default_kind", ctx.default_value_kind, 2.5)
    if ctx.function_name:
        add("function_name", ctx.function_name, 1.5)
    if ctx.class_name:
        add("class_name", ctx.class_name, 1.0)

    add_many("decorators", ctx.decorators,          1.5)
    add_many("fn_flags",   ctx.function_name_flags, 2.0)

    sibling_names = [n for n, _ in ctx.sibling_params]
    sibling_types = [t for _, t in ctx.sibling_params if t]
    add_many("sibling_names", sibling_names, 1.5)
    add_many("sibling_types", sibling_types, 2.0)

    add_many("attributes", ctx.attribute_accesses, 1.0)

    usage_flags: list[str] = []
    if ctx.is_iterated:      usage_flags.append("iterated")
    if ctx.is_indexed:       usage_flags.append("indexed")
    if ctx.is_called:        usage_flags.append("called")
    if ctx.is_none_compared: usage_flags.append("none_compared")
    add_many("usage_flags", usage_flags, 1.0)

    return " ".join(parts) if parts else "*"


class TypeRetriever:
    """Wraps a Tantivy index and exposes fast type prediction."""

    def __init__(self, index_dir: str | Path):
        index_dir = Path(index_dir)
        if not index_dir.exists():
            raise FileNotFoundError(f"Index not found: {index_dir}")
        self._index = tantivy.Index(_make_schema(), path=str(index_dir))
        self._index.reload()
        self._searcher = self._index.searcher()

    def query(self, ctx: QueryContext, top_k: int = 5,
              fetch_hits: int = 50) -> list[TypeCandidate]:
        query_str = _build_query_str(ctx)
        try:
            q = self._index.parse_query(query_str, _SEARCH_FIELDS)
            hits = self._searcher.search(q, fetch_hits).hits
        except Exception:
            return []

        if not hits:
            return []

        agg: dict[str, list] = {}
        for score, addr in hits:
            doc = self._searcher.doc(addr)
            ann_type = doc.get_first("annotated_type") or ""
            if not ann_type:
                continue
            source = doc.get_first("source_file") or ""
            line   = doc.get_first("line") or 0
            if ann_type not in agg:
                agg[ann_type] = [0.0, 0, source, line]
            agg[ann_type][0] += score
            agg[ann_type][1] += 1

        ranked = sorted(agg.items(), key=lambda x: x[1][0], reverse=True)
        return [
            TypeCandidate(
                annotated_type=t,
                score=round(s, 4),
                hit_count=c,
                source_file=src,
                line=ln,
            )
            for t, (s, c, src, ln) in ranked[:top_k]
        ]

    def reload(self) -> None:
        self._index.reload()
        self._searcher = self._index.searcher()
