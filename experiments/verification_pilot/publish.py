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


def publish_model(
    store: ObjectStore, manifest_refs: Sequence[str], destination: Path, *,
    model: str, own_group: str, tier2_refs: Sequence[str] = (),
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
        raw_bytes = sum(path.stat().st_size for path in bundle.objects.iterdir())
        notice = destination / f"{hypothesis.lower()}-review.txt"
        if raw_bytes > MAX_EXPORT_BYTES:
            notice.write_text(
                "Static review exceeds Assay's 64 MiB export cap. Open this "
                "verified bundle with the local Assay review server.\n", encoding="utf-8"
            )
        else:
            try:
                export_review(store, ref, destination / f"{hypothesis.lower()}-review.html")
            except ExportError as error:
                if error.code != "export_budget_exceeded":
                    raise
                notice.write_text(
                    "Static review exceeds Assay's 64 MiB export cap. Open this "
                    "verified bundle with the local Assay review server.\n", encoding="utf-8"
                )
    (destination / "report.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result
