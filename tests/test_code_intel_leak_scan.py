"""Pre-run scanner inspects manifest and deliverable source text."""

from assay.code_intel.leak_scan import scan_pre_run, scan_text
from assay.code_intel.models import ContextItem, PreloadedSummary, QueryResult
from assay.code_intel.snapshot import make_index_manifest

REVISION = "sha256:" + "3" * 64


def test_scan_text_keeps_historical_context_window() -> None:
    text = "a" * 90 + "hidden\ntest" + "b" * 90
    hits = scan_text(text, [r"hidden[ _-]?test"], (), source="message")
    assert len(hits) == 0
    hits = scan_text(text, [r"hidden\ntest"], (), source="message")
    assert len(hits) == 1
    assert hits[0].context == "a" * 80 + "hidden test" + "b" * 80


def test_scan_pre_run_covers_manifest_summary_and_queries() -> None:
    tree = {"src/main.ts": "x"}
    manifest = make_index_manifest(
        tree, image_digest=REVISION, indexer_version="v1", excluded_paths=(),
        indexed_paths=tree,
    )
    item = ContextItem(
        repo_revision=manifest.repo_revision, file_path="src/main.ts", retrieval_method="symbol",
        rank=0, content_hash=REVISION, approximate_tokens=2,
        raw_source_ref="src/main.ts:1", content="planted value",
    )
    summary = PreloadedSummary(repo_revision=manifest.repo_revision, text="oracle note")
    result = QueryResult(query_kind="symbol", items=(item,))
    hits = scan_pre_run(manifest, summary, (result,), ("oracle", "planted"), ())
    assert [(hit.source, hit.term) for hit in hits] == [
        ("summary", "oracle"), ("query:0", "planted")
    ]


def test_scan_pre_run_finds_declared_hidden_source_text() -> None:
    tree = {"src/main.ts": "x"}
    manifest = make_index_manifest(
        tree, image_digest=REVISION, indexer_version="v1", excluded_paths=(),
        indexed_paths=tree,
    )
    summary = PreloadedSummary(repo_revision=manifest.repo_revision, text="answer\nline")
    hits = scan_pre_run(manifest, summary, (), (), (), ("answer\nline",))
    assert len(hits) == 1
    assert hits[0].source == "summary"
    upper_summary = PreloadedSummary(repo_revision=manifest.repo_revision, text="ANSWER\nLINE")
    assert scan_pre_run(manifest, upper_summary, (), (), (), ("answer\nline",)) == ()
