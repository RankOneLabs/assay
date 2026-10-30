"""Extension-labelled scan of bytes deliverable to a worker."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from assay.code_intel.leak_scan import scan_text
from code_extension.bridge import EXTENSION_SYSTEM_PROMPT
from code_extension.fixtures import ScenarioFixture

TERMS = (
    r"tests/hidden/",
    r"hidden/new_behavior/",
    r"hidden/regression/",
    r"patches/(?:reference|missing-registration|missing-validation|missing-type-export)\.patch",
    r"assay-extension-qualification-record/",
    r"reference_solution",
)


def scan_delivery(
    fixture: ScenarioFixture,
    tool_outputs: Iterable[str] = (),
    extra_text: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Keep only bounded hit metadata; successful scans carry no private source."""
    sources = {f"repository/{name}": source for name, source in fixture.repository.items()}
    sources.update({"rendered_task": fixture.task, "system_prompt": EXTENSION_SYSTEM_PROMPT})
    sources.update({f"tool_output/{index}": value for index, value in enumerate(tool_outputs)})
    if extra_text:
        sources.update(extra_text)
    hidden_paths = tuple(name for group in fixture.groups[1:] for name in group.files)
    hits = [
        hit
        for label, content in sorted(sources.items())
        for hit in scan_text(content, TERMS, hidden_paths, source=label)
    ]
    return {
        "schema_version": "assay-extension-leak-scan/0.1.0",
        "subject_id": fixture.subject_id,
        "sources_scanned": len(sources),
        "hits": [dict(source=hit.source, term=hit.term, context=hit.context) for hit in hits],
    }
