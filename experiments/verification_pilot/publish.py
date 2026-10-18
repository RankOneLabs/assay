"""Write a reviewable pilot report and offline-verifiable export bundles."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from assay.review.export import MAX_EXPORT_BYTES, ExportError, export_review
from assay.store import ObjectStore
from assay.verify import export_bundle, verify_bundle
from verification_pilot.render import (
    merge_study_tables,
    read_study_state,
    render_study_pages,
)
from verification_pilot.report import model_report


def _write_review_export(
    store: ObjectStore, ref: str, objects: Path, destination: Path, hypothesis: str,
) -> dict[str, Any]:
    raw_bytes = sum(path.stat().st_size for path in objects.iterdir())
    review: dict[str, Any] = {"closure_bytes": raw_bytes, "cap_bytes": MAX_EXPORT_BYTES}
    notice = destination / f"{hypothesis.lower()}-review.txt"
    if raw_bytes <= MAX_EXPORT_BYTES:
        try:
            export_review(store, ref, destination / f"{hypothesis.lower()}-review.html")
            review["status"] = "html"
            return review
        except ExportError as error:
            if error.code != "export_budget_exceeded":
                raise
    review["status"] = "over_cap"
    notice.write_text(
        "Static review exceeds Assay's 64 MiB export cap. Open this "
        "verified bundle with the local Assay review server.\n", encoding="utf-8",
    )
    return review


def publish_model(
    store: ObjectStore, manifest_refs: Sequence[str], destination: Path, *,
    model: str, own_group: str, tier2_refs: Sequence[str] = (),
    qualified: bool = False, study_page: Path | None = None,
) -> dict[str, Any]:
    """Publish the model's tables, source manifests, and engine report views.

    Each bundle is an exact reference closure, so ``assay verify`` works after
    copying it away from the original store. The pilot's H1/H4 calculations
    are explicit in report.json and remain recomputable from manifest bundles.
    """
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("publication destination must be empty")
    result = model_report(store, manifest_refs, model=model, own_group=own_group,
                          tier2_refs=tier2_refs)
    destination.mkdir(parents=True, exist_ok=True)
    result["review_exports"] = {}
    for index, ref in enumerate((*manifest_refs, *tier2_refs), 1):
        bundle = export_bundle(store, ref, destination / f"manifest-{index}")
        failures = tuple(f for f in verify_bundle(bundle, ref) if f.code != "incomplete_run")
        if failures:
            raise ValueError(f"offline manifest verification failed: {failures}")
    for hypothesis in ("H2", "H3"):
        detail = result[hypothesis]
        if "report_ref" not in detail:
            continue
        ref = str(detail["report_ref"])
        bundle = export_bundle(store, ref, destination / hypothesis.lower())
        if verify_bundle(bundle, ref):
            raise ValueError(f"offline report verification failed for {hypothesis}")
        result["review_exports"][hypothesis] = _write_review_export(
            store, ref, bundle.objects, destination, hypothesis,
        )
    (destination / "report.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    tables = result["analysis"]
    qualified_routes: frozenset[str] = frozenset()
    if qualified:
        page = study_page or (Path(__file__).resolve().parents[2]
                              / "studies/verification-pilot/README.md")
        supporting_page = page.with_name("supporting-data.md")
        if not supporting_page.exists() and page.exists() and "| qualified |" in page.read_text():
            raise ValueError("published study page lacks recoverable route tables")
        previous, prior_qualified = read_study_state(supporting_page, own_group=own_group)
        tables = merge_study_tables(previous, tables)
        qualified_routes = prior_qualified | frozenset({model})
    main, supporting = render_study_pages(tables, qualified_routes=qualified_routes)
    (destination / "study.md").write_text(main, encoding="utf-8")
    (destination / "supporting-data.md").write_text(supporting, encoding="utf-8")
    if qualified:
        page.write_text(main, encoding="utf-8")
        supporting_page.write_text(supporting, encoding="utf-8")
    return result
