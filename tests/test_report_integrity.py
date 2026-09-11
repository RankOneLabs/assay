from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from test_execution import execution_fixture

from assay.canonical import canonical_json, digest_bytes
from assay.execution import EvaluationSuccess, RunSucceeded, execute_plan
from assay.models import Exclusion, ReportConfig, StatisticalProfile
from assay.planning import compile_plan
from assay.report_engine import ReportError, build_report, summarize_operating
from assay.store import ObjectStore
from assay.verify import verify_manifest


@pytest.mark.parametrize("change_payload", [False, True])
async def test_cross_run_pairing_binds_subject_digest_to_payload(
    tmp_path: Path, change_payload: bool
) -> None:
    """Complementary exclusions cannot conceal drift in a subject's reference labels."""
    fixture = execution_fixture(ObjectStore(tmp_path), subject_ids=("ok",), worker_repeats=1)
    store = fixture.store
    declaration = fixture.snapshot.evaluators[0]
    companion = json.loads(store.read_bytes(declaration.payload_schema_ref))
    companion["allOf"][1]["properties"]["verdict"]["properties"]["value"] = {
        "enum": ["bad", "good"]
    }
    declaration = declaration.model_copy(
        update={"payload_schema_ref": str(store.publish_json(companion))}
    )

    class Labels:
        def configuration(self) -> dict[str, Any]:
            return {"version": "quality-v1"}

        async def evaluate(self, **kwargs: Any) -> EvaluationSuccess:
            return EvaluationSuccess("good" if kwargs["output"]["score"] else "bad")

    results = []
    for index, excluded_arm in enumerate(("candidate", "reference")):
        label = "good" if change_payload and index == 1 else "bad"
        # The synthetic digest intentionally remains identical while the separately
        # referenced payload changes. Each individual run is internally valid.
        subject = fixture.snapshot.subjects[0].model_copy(
            update={"payload_ref": str(store.publish_json({"subject": "ok", "label": label}))}
        )
        snapshot = fixture.snapshot.model_copy(
            update={"subjects": (subject,), "evaluators": (declaration,)}
        )
        snapshot_ref = str(store.publish_json(snapshot.model_dump(mode="json")))
        plan = compile_plan(
            snapshot,
            snapshot_ref=snapshot_ref,
            worker_repeats=1,
            jig_revision="55081e8",
            exclusions=(
                Exclusion(
                    subject_id="ok",
                    arm_id=excluded_arm,
                    classification="split_run",
                    reason="complementary arm allocation",
                ),
            ),
        )
        plan_bytes = canonical_json(plan.model_dump(mode="json"))
        result = await execute_plan(
            **(
                fixture.arguments
                | {
                    "snapshot": snapshot,
                    "plan_bytes": plan_bytes,
                    "authorization": digest_bytes(plan_bytes),
                    "evaluators": {"quality": Labels()},
                }
            )
        )
        assert isinstance(result, RunSucceeded), result
        assert verify_manifest(store, str(result.manifest_ref)) == ()
        results.append(result)
    config = ReportConfig(
        manifest_refs=tuple(str(result.manifest_ref) for result in results),
        record_refs=tuple(
            ref for result in results for ref in result.manifest.evaluation_records.values()
        ),
        reference_arm="reference",
        candidates=("candidate",),
        evaluator_id="quality",
        metric="classification",
        categories=("bad", "good"),
        positive_label="good",
        evaluator_repeat_aggregation="majority",
        worker_repeat_aggregation="majority",
        statistical_profile=StatisticalProfile(seed=1, bootstrap_samples=100),
        engine_version="0.1.0",
    )
    if change_payload:
        with pytest.raises(ReportError, match="subject"):
            build_report(store, config)
    else:
        comparison = build_report(store, config)["comparisons"][0]
        assert comparison["n"] == 1
        assert comparison["reference_metrics"]["accuracy"] == 1.0
        assert comparison["candidate_metrics"]["accuracy"] == 0.0


async def test_cost_summary_rejects_price_claimed_as_unavailable(tmp_path: Path) -> None:
    fixture = execution_fixture(ObjectStore(tmp_path), subject_ids=("ok",), worker_repeats=1)
    result = await execute_plan(**fixture.arguments)
    assert isinstance(result, RunSucceeded), result
    record_ref = next(iter(result.manifest.operating_records.values()))
    record = json.loads(fixture.store.read_bytes(record_ref))
    record["price"] = {"currency": "USD", "amount": 10, "basis": "fixture-price"}
    altered_ref = str(fixture.store.publish_json(record))
    with pytest.raises(ReportError, match="unavailable"):
        summarize_operating(fixture.store, [altered_ref])
