"""Deterministic, self-contained HTML exports for one review root."""

from __future__ import annotations

import base64
import os
import re
import tempfile
from collections.abc import Iterable, Mapping
from contextlib import suppress
from dataclasses import fields, is_dataclass, replace
from pathlib import Path
from typing import cast
from urllib.parse import quote

from assay._version import __version__
from assay.canonical import canonical_json
from assay.review import index as review_index
from assay.review import read as review_read
from assay.review.model import (
    EmbeddedObject,
    ExportData,
    JSONValue,
    ReadIssue,
    ReportDetail,
    ReportSummary,
    StoreSummary,
    canonical_view_json,
    to_json_value,
)
from assay.store import ObjectStore, verification_session

MAX_EXPORT_BYTES = 64 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024
_STATIC = Path(__file__).with_name("static")
_FATAL_READ_CODES = frozenset(
    {"integrity_error", "invalid_record", "missing_config", "missing_object"}
)


class ExportError(ValueError):
    """A stable, reference-attributed failure to produce an export."""

    def __init__(self, code: str, message: str, ref: str | None = None) -> None:
        self.code = code
        self.ref = ref
        suffix = f" ({ref})" if ref is not None and ref not in message else ""
        super().__init__(f"{code}: {message}{suffix}")


def _base64_size(size: int) -> int:
    return 4 * ((size + 2) // 3)


def _view_mapping_size(views: Mapping[str, JSONValue]) -> int:
    """Measure a canonical JSON object without constructing the whole object string."""
    if not views:
        return 2
    return 1 + sum(
        len(canonical_json(key)) + 1 + len(canonical_view_json(views[key]))
        for key in sorted(views)
    ) + len(views) - 1 + 1


def compute_export_budget(
    closure_bytes: Mapping[str, bytes], views: Mapping[str, JSONValue]
) -> int:
    """Compute the export budget before base64 or ExportData serialization."""
    raw_total = sum(len(raw) for raw in closure_bytes.values())
    downloads = sum(
        _base64_size(len(raw))
        for raw in closure_bytes.values()
        if len(raw) <= MAX_DOWNLOAD_BYTES
    )
    return raw_total + downloads + _view_mapping_size(views)


def escape_html_boundary(text: str) -> str:
    """Escape JSON once, at its sole boundary with the HTML parser."""
    return (
        text.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _encoded(value: str) -> str:
    return quote(value, safe="")


def _run_path(run_key: str) -> str:
    return f"/api/runs/{_encoded(run_key)}"


def _cell_path(run_key: str, cell_id: str) -> str:
    return f"{_run_path(run_key)}/cells/{_encoded(cell_id)}"


def _pair_path(run_key: str, subject_id: str, reference: str, candidate: str) -> str:
    return (
        f"{_run_path(run_key)}/pairs/{_encoded(subject_id)}"
        f"?reference={_encoded(reference)}&candidate={_encoded(candidate)}"
    )


def _report_path(report_ref: str) -> str:
    return f"/api/reports/{_encoded(report_ref)}"


def _issues(value: object) -> Iterable[ReadIssue]:
    if isinstance(value, ReadIssue):
        yield value
    elif is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            yield from _issues(getattr(value, field.name))
    elif isinstance(value, dict):
        for item in value.values():
            yield from _issues(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _issues(item)


def _check_read_issues(values: Iterable[object]) -> None:
    failures = sorted(
        (
            issue
            for value in values
            for issue in _issues(value)
            if issue.code in _FATAL_READ_CODES
        ),
        key=lambda issue: (issue.code, issue.ref or "", issue.message),
    )
    if failures:
        issue = failures[0]
        raise ExportError(issue.code, issue.message, issue.ref)


def _offline_report(summary: ReportSummary) -> ReportSummary:
    issues = summary.issues
    if summary.engine_version is not None and summary.engine_version != __version__:
        issues = (
            *issues,
            ReadIssue(
                "unsupported_engine",
                f"report engine {summary.engine_version} is not installed",
                summary.report_ref,
                None,
            ),
        )
    return replace(
        summary,
        recomputable=False,
        recompute_disabled_reason="Requires the local Assay server",
        issues=issues,
    )


def _root_index(
    store: ObjectStore, root_ref: str, raw_by_ref: Mapping[str, bytes]
) -> review_index.ReviewIndex:
    classified: list[review_index.IndexedObject] = []
    for ref in sorted(raw_by_ref):
        item = review_index.classify_object(ref, raw_by_ref[ref])
        if isinstance(item, ReadIssue):
            raise ExportError("invalid_record", item.message, item.ref)
        classified.append(item)
    by_ref = {item.ref: item for item in classified}
    manifests = [
        item for item in classified if isinstance(item, review_index.IndexedManifest)
    ]
    reports = [item for item in classified if isinstance(item, review_index.IndexedReport)]
    root = by_ref.get(root_ref)
    if not isinstance(root, review_index.IndexedManifest | review_index.IndexedReport):
        raise ExportError(
            "unsupported_root", "root must be an Assay manifest or report", root_ref
        )
    runs = tuple(
        sorted(
            (review_index.manifest_run(item, by_ref, store) for item in manifests),
            key=lambda run: run.run_key,
        )
    )
    summaries = tuple(
        sorted(
            (review_index.report_summary(item, by_ref) for item in reports),
            key=lambda report: report.report_ref,
        )
    )
    return review_index.ReviewIndex(
        root_ref, tuple(classified), runs, summaries, (), False
    )


def _assemble_views(
    reader: review_read.ReviewReader, root_ref: str
) -> tuple[StoreSummary, dict[str, JSONValue]]:
    root = next(item for item in reader.index.objects if item.ref == root_ref)
    source_values: list[object] = []
    views: dict[str, JSONValue] = {}
    run_details = [reader.run(run.run_key) for run in reader.index.runs]
    reports: list[ReportDetail] = []
    if isinstance(root, review_index.IndexedReport):
        report_detail = reader.report(root_ref)
        report_detail = replace(
            report_detail, summary=_offline_report(report_detail.summary)
        )
        reports.append(report_detail)
        views[_report_path(root_ref)] = to_json_value(report_detail)

    report_summaries = tuple(report.summary for report in reports)
    store_summary = replace(
        reader.store_summary(), root=None, reports=report_summaries
    )
    views["/api/store"] = to_json_value(store_summary)

    for run_detail in run_details:
        source_values.append(run_detail)
        views[_run_path(run_detail.summary.run_key)] = to_json_value(run_detail)
        cell_keys: dict[str, str] = {}
        for summary in run_detail.cells:
            cell = reader.cell(run_detail.summary.run_key, summary.cell_id)
            source_values.append(cell)
            cell_path = _cell_path(run_detail.summary.run_key, summary.cell_id)
            cell_keys[summary.cell_id] = cell_path
            views[cell_path] = to_json_value(cell)
        for subject in run_detail.subjects:
            for reference in run_detail.arms:
                for candidate in run_detail.arms:
                    if reference.id == candidate.id:
                        continue
                    pair = reader.pair(
                        run_detail.summary.run_key,
                        subject.id,
                        reference_arm=reference.id,
                        candidate_arm=candidate.id,
                    )
                    source_values.append(pair)
                    pair_value = cast(dict[str, JSONValue], to_json_value(pair))
                    for side in ("reference_cells", "candidate_cells"):
                        cells = getattr(pair, side)
                        keys: list[JSONValue] = []
                        for cell in cells:
                            referenced_path = cell_keys.get(cell.summary.cell_id)
                            if referenced_path is None:
                                referenced_path = _cell_path(
                                    run_detail.summary.run_key, cell.summary.cell_id
                                )
                                cell_keys[cell.summary.cell_id] = referenced_path
                                views[referenced_path] = to_json_value(cell)
                            keys.append(referenced_path)
                        pair_value[side] = keys
                    views[
                        _pair_path(
                            run_detail.summary.run_key,
                            subject.id,
                            reference.id,
                            candidate.id,
                        )
                    ] = pair_value

    ambiguities = reader.ambiguities()
    source_values.extend((*reports, store_summary, ambiguities))
    views["/api/ambiguities"] = to_json_value(ambiguities)
    _check_read_issues(source_values)
    return store_summary, {key: views[key] for key in sorted(views)}


def build_export_data(store: ObjectStore, root_ref: str) -> ExportData:
    """Build the complete export model from one verified reference closure."""
    session = verification_session(store)
    closure, failures = review_read.closure(session, root_ref)
    if failures:
        failure = sorted(failures, key=lambda item: (item.code, item.message))[0]
        match = re.search(r"sha256:[0-9a-f]{64}", failure.message)
        ref = match.group(0) if match else root_ref
        raise ExportError(failure.code, failure.message, ref)
    raw_by_ref = {ref: session.read_bytes(ref) for ref in sorted(closure)}

    index = _root_index(session, root_ref, raw_by_ref)
    reader = review_read.ReviewReader(session, index)
    store_summary, views = _assemble_views(reader, root_ref)
    budget = compute_export_budget(raw_by_ref, views)
    if budget > MAX_EXPORT_BYTES:
        raise ExportError(
            "export_budget_exceeded",
            f"static export requires {budget} bytes, exceeding the 64 MiB cap; "
            "use the local Assay server",
            root_ref,
        )

    objects: dict[str, EmbeddedObject] = {}
    for ref, raw in sorted(raw_by_ref.items()):
        downloadable = len(raw) <= MAX_DOWNLOAD_BYTES
        objects[ref] = EmbeddedObject(
            review_read.preview(session, ref),
            base64.b64encode(raw).decode("ascii") if downloadable else None,
            None
            if downloadable
            else "Download unavailable because the object exceeds 8 MiB",
        )
    return ExportData(
        "assay-review-export/0.1.0",
        root_ref,
        store_summary,
        views,
        objects,
        {"recompute": False, "refresh": False, "verify": False},
    )


def _trusted_asset(path: Path, closing_tag: str) -> str:
    text = path.read_text(encoding="utf-8")
    if re.search(rf"</\s*{closing_tag}\b", text, re.IGNORECASE):
        raise ExportError(
            "unsafe_frontend", f"inline frontend contains a closing {closing_tag} tag"
        )
    return text


def _document(data: ExportData) -> bytes:
    css = _trusted_asset(_STATIC / "app.css", "style")
    javascript = _trusted_asset(_STATIC / "offline.js", "script")
    encoded = canonical_view_json(data).decode("utf-8")
    payload = escape_html_boundary(encoded)
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Assay review</title>
<style>{css}</style>
</head>
<body>
<header class="site-header"><a href="#/" class="brand">Assay review</a>
<nav aria-label="Primary"><a href="#/">Runs</a>
<a href="#/ambiguities">Ambiguity queue</a></nav></header>
<main id="app" aria-live="polite"></main>
<noscript>This review requires JavaScript.</noscript>
<script id="assay-review-data" type="application/json" data-assay-review>{payload}</script>
<script type="module">{javascript}</script>
</body>
</html>
"""
    return html.encode("utf-8")


def export_review(store: ObjectStore, root_ref: str, destination: str | Path) -> Path:
    """Atomically publish one deterministic static review document."""
    target = Path(destination)
    if target.exists():
        raise ExportError("destination_exists", "destination already exists")
    document = _document(build_export_data(store, root_ref))
    temporary: str | None = None
    try:
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(document)
            stream.flush()
            os.fsync(stream.fileno())
        if target.exists():
            raise ExportError("destination_exists", "destination already exists")
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            with suppress(FileNotFoundError):
                os.unlink(temporary)
    return target


export_html = export_review
