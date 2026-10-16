"""Write a reviewable pilot report and offline-verifiable export bundles."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from assay.review.export import MAX_EXPORT_BYTES, ExportError, export_review
from assay.store import ObjectStore
from assay.verify import export_bundle, verify_bundle
from verification_pilot.report import model_report


def _publish_qualified_ceiling(page: Path, model: str, rows: list[dict[str, Any]]) -> None:
    """Fill the route's cells after its manual smoke qualification."""
    text = page.read_text(encoding="utf-8")
    start = "<!-- ceiling-table:start -->"
    end = "<!-- ceiling-table:end -->"
    before, marker, remaining = text.partition(start)
    if not marker or end not in remaining:
        raise ValueError("study page has no ceiling table markers")
    current, _, after = remaining.partition(end)
    lines = current.strip().splitlines()
    by_arm = {str(row["arm"]): row for row in rows}
    if set(by_arm) != {"t1-native", "t1-quoted"}:
        raise ValueError("qualified route requires both Tier 1 ceiling cells")

    def cell(arm: str) -> str:
        row = by_arm[arm]
        count, n = int(row["repository_wide_first"]), int(row["n"])
        if n <= 0:
            raise ValueError("qualified route has no observed Tier 1 cells")
        return f"{count}/{n} ({count / n:.1%})"

    replacement = f"| {model} | {cell('t1-native')} | {cell('t1-quoted')} | qualified |"
    route_prefix = f"| {model} |"
    for index, line in enumerate(lines):
        if line.startswith(route_prefix):
            lines[index] = replacement
            break
    else:
        lines.append(replacement)
    page.write_text(before + start + "\n" + "\n".join(lines) + "\n" + end + after,
                    encoding="utf-8")


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
    if qualified:
        page = study_page or (Path(__file__).resolve().parents[2]
                              / "studies/verification-pilot/README.md")
        _publish_qualified_ceiling(page, model, result["ceiling_effect"])
    return result
