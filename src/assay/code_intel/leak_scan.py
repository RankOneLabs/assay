"""Pure pre-run scan of text exposed by an index, summary, or query."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from assay.code_intel.models import IndexManifest, PreloadedSummary, QueryResult


@dataclass(frozen=True)
class LeakHit:
    source: str
    term: str
    context: str
    start: int
    end: int


def scan_text(
    text: str, term_patterns: Sequence[str], hidden_paths: Iterable[str], *, source: str,
) -> tuple[LeakHit, ...]:
    """Use the historical 80-character window and newline replacement."""
    patterns = [re.compile(term, re.I) for term in term_patterns]
    patterns.extend(re.compile(re.escape(path)) for path in sorted(set(hidden_paths)))
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
    # Serialized wire models escape newlines; search for the fixture's declared
    # hidden_tests source in the same encoding as the material being scanned.
    patterns = [*term_patterns, *(re.escape(json.dumps(source, ensure_ascii=False)[1:-1])
                                 for source in hidden_source_texts if source)]
    return tuple(hit for source, content in sources
                 for hit in scan_text(content, patterns, paths, source=source))
