"""Pure pre-run scan of text exposed by an index, summary, or query."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache

from assay.code_intel.models import IndexManifest, PreloadedSummary, QueryResult


@dataclass(frozen=True)
class LeakHit:
    source: str
    term: str
    context: str
    start: int
    end: int


@lru_cache(maxsize=128)
def _compiled_patterns(
    terms: tuple[str, ...], paths: tuple[str, ...],
) -> tuple[re.Pattern[str], ...]:
    return (*[re.compile(term, re.I) for term in terms],
            *[re.compile(re.escape(path)) for path in paths])


def scan_text(
    text: str, term_patterns: Sequence[str], hidden_paths: Iterable[str], *, source: str,
) -> tuple[LeakHit, ...]:
    """Use the historical 80-character window and newline replacement."""
    patterns = _compiled_patterns(tuple(term_patterns), tuple(sorted(set(hidden_paths))))
    return tuple(
        LeakHit(
            source=source, term=pattern.pattern,
            context=text[max(0, match.start() - 80):match.end() + 80].replace("\n", " "),
            start=match.start(), end=match.end(),
        )
        for pattern in patterns for match in pattern.finditer(text)
    )


def scan_pre_run(
    manifest: IndexManifest, summary: PreloadedSummary | None,
    query_results: Sequence[QueryResult], term_patterns: Sequence[str],
    hidden_paths: Iterable[str], hidden_source_texts: Iterable[str] = (),
) -> tuple[LeakHit, ...]:
    """Inspect the full manifest and all content that may be delivered before a run."""
    sources = [("index_manifest", manifest.model_dump_json())]
    if summary is not None:
        sources.append(("summary", summary.model_dump_json()))
    for position, result in enumerate(query_results):
        sources.append((f"query:{position}", result.model_dump_json()))
    paths = tuple(hidden_paths)
    # Serialized wire models escape newlines. Match declared hidden source text
    # in that same encoding and with its exact case; only study terms use re.I.
    hidden_literals = tuple(json.dumps(source, ensure_ascii=False)[1:-1]
                            for source in hidden_source_texts if source)
    hits: list[LeakHit] = []
    for source, content in sources:
        hits.extend(scan_text(content, term_patterns, paths, source=source))
        for literal in hidden_literals:
            start = 0
            while (position := content.find(literal, start)) != -1:
                end = position + len(literal)
                hits.append(LeakHit(
                    source=source, term=re.escape(literal),
                    context=content[max(0, position - 80):end + 80].replace("\n", " "),
                    start=position, end=end,
                ))
                start = end
    return tuple(hits)
