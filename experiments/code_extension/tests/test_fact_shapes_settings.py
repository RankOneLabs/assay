"""Fact-shapes settings and mechanical library rerun verdict."""

import base64
import json
from decimal import Decimal
from pathlib import Path

import pytest
from code_extension.fact_shapes.library_rerun import RerunRow, verdict
from code_extension.reachability import _request_timeout

from assay.canonical import digest_bytes
from assay.models import ExecutionOutcome
from assay.store import ObjectStore


@pytest.mark.parametrize(
    "terminal",
    [
        "request_limit",
        "turn_limit",
        "output_token_limit",
        "conversation_limit",
        "wall_limit",
        "request_timeout",
    ],
)
def test_one_limit_passes(terminal: str) -> None:
    outcome = (
        "timeout"
        if terminal == "wall_limit"
        else ("harness_failure" if terminal == "request_timeout" else "limit_stop")
    )
    result = verdict(
        [
            {
                "outcome": outcome,
                "terminal": terminal,
                "request_timeout": terminal == "request_timeout",
            },
            *({"outcome": "passed"} for _ in range(10)),
        ]
    )
    assert (result.status, result.limit_stop_count, result.settled_count) == ("passed", 1, 11)


def test_settlement_and_failure_threshold() -> None:
    assert verdict([RerunRow(outcome="passed")] * 11).status == "passed"
    assert verdict([RerunRow(outcome="semantic")] * 11).limit_stop_count == 0
    for count in (9, 11):
        result = verdict(
            [RerunRow(outcome="limit_stop")] * 2 + [RerunRow(outcome="passed")] * (count - 2)
        )
        assert (result.status, result.limit_stop_count, result.settled_count) == (
            "failed",
            2,
            count,
        )
    rows = [
        RerunRow(outcome="limit_stop"),
        *[RerunRow(outcome="passed")] * 9,
        RerunRow(outcome="unsettled", request_timeout=True),
    ]
    assert verdict(rows).status == "incomplete"
    assert verdict(rows).settled_count == 10
    assert verdict(rows).limit_stop_count == 1
    with pytest.raises(ValueError, match="eleven"):
        verdict([RerunRow(outcome="passed")] * 12)


@pytest.mark.parametrize(
    "exception",
    [
        "ReadTimeout",
        "ConnectTimeout",
        "WriteTimeout",
        "PoolTimeout",
        "TimeoutException",
        "ConnectError",
    ],
)
def test_timeout_identity_survives_trace(tmp_path: Path, exception: str) -> None:
    store = ObjectStore(tmp_path)
    raw = json.dumps(
        {"events": [{"kind": "stopped", "cause": "transport_failure", "error": exception}]}
    ).encode()
    artifact = str(
        store.publish_json(
            {
                "schema_version": "assay-pier-raw-artifact/0.1.0",
                "checksum": digest_bytes(raw),
                "byte_length": len(raw),
                "content_base64": base64.b64encode(raw).decode(),
            }
        )
    )
    trace = str(
        store.publish_json(
            {
                "bridge_outcome": {"kind": "infrastructure_failure", "cause": "enforcement"},
                "artifact_refs": {"trajectory.json": artifact},
            }
        )
    )
    outcome = ExecutionOutcome.model_construct(status="failed", trace_ref=trace)
    assert _request_timeout(outcome, store) == (exception != "ConnectError")


def test_routes_and_pilot_allocation() -> None:
    from collections import Counter

    from assay_pier_bridge.agent_loop import PAID_TURN_ROUTES
    from code_extension.bridge import AUTHORIZED_MODEL_ROUTES
    from code_extension.fact_shapes.settings import FACT_SHAPES, PILOT_ALLOCATION, STUDY_MODELS
    from code_extension.settings import ExtensionAgentSettings

    assert {model.name for model in STUDY_MODELS} == {"sol", "argon", "midtier"}
    for model in STUDY_MODELS:
        route = model.route
        assert (route.endpoint, route.model, route.provider) in AUTHORIZED_MODEL_ROUTES
        assert (route.model, route.provider) in PAID_TURN_ROUTES
        bounds = ExtensionAgentSettings.for_model(route.model, envelope="fact-shapes-v1")
        assert (bounds.max_turns, bounds.timeout_s, bounds.request_timeout_s) == (80, 1800, 120)
        assert (bounds.max_output_tokens, bounds.max_tool_output_bytes) == (8192, 32768)
        assert bounds.concurrency == bounds.attempts == 1
        assert bounds.provider_retries == bounds.sdk_retries == 0
        cells = [cell for cell in PILOT_ALLOCATION if cell.model == model.name]
        assert {cell.shape for cell in cells} == set(FACT_SHAPES)
        assert all(cell.task_type == "additive" for cell in cells)
        assert all(cell.attempts == (2 if model.name == "sol" else 1) for cell in cells)
    totals: Counter[str] = Counter()
    for cell in PILOT_ALLOCATION:
        totals[cell.model] += cell.attempts
    assert totals == {"sol": 12, "argon": 6, "midtier": 6}
    assert totals.total() == 24


@pytest.mark.parametrize("amount", ["0", "-1", "NaN", "Infinity"])
def test_caps_require_positive_finite_dollars(amount: str) -> None:
    from code_extension.fact_shapes.settings import PerAttemptCaps

    with pytest.raises(ValueError):
        PerAttemptCaps(sol=Decimal(amount), argon=Decimal(1), midtier=Decimal(1))


def test_approved_caps_and_observation_provenance() -> None:
    from code_extension.fact_shapes.settings import (
        LIBRARY_RERUN_TOTAL_CAP_USD,
        PER_ATTEMPT_CAPS,
        PILOT_TOTAL_CAP_USD,
        QWEN_OBSERVATION_CITATION,
        STUDY_MODELS,
    )

    assert PER_ATTEMPT_CAPS.model_dump() == {
        "sol": Decimal("2"),
        "argon": Decimal("4"),
        "midtier": Decimal("1"),
    }
    assert all(getattr(PER_ATTEMPT_CAPS, model.name) > 0 for model in STUDY_MODELS)
    assert Decimal("61") == PILOT_TOTAL_CAP_USD
    assert Decimal("5") == LIBRARY_RERUN_TOTAL_CAP_USD
    assert QWEN_OBSERVATION_CITATION
    assert "original receipt unavailable" in QWEN_OBSERVATION_CITATION


def test_library_rerun_matches_qualified_manifests_and_cohort() -> None:
    from code_extension.config import RunConfiguration
    from code_extension.fact_shapes.settings import (
        LIBRARY_RERUN_TOTAL_CAP_USD,
        PER_ATTEMPT_CAPS,
        STUDY_ENVELOPE,
        STUDY_MODELS,
    )
    from code_extension.fixture import PILOT
    from code_extension.launch import CohortRequest
    from code_extension.protocol import ORDERED_TOOL_SCHEMAS_SHA256, SYSTEM_PROMPT_SHA256
    from code_extension.settings import ExtensionAgentSettings

    directory = Path(__file__).resolve().parents[1] / "studies/fact-shapes-2026-11"
    config = RunConfiguration.load(directory / "library-rerun-midtier.json")
    midtier = next(model for model in STUDY_MODELS if model.name == "midtier")
    assert config.route == midtier.route
    assert config.envelope == STUDY_ENVELOPE
    assert config.bounds == ExtensionAgentSettings.for_model(
        midtier.route.model,
        envelope=STUDY_ENVELOPE,
    )
    assert config.repeats == config.concurrency == 1
    assert config.profile == "openrouter"
    assert config.system_prompt_digest == SYSTEM_PROMPT_SHA256
    assert config.tool_schemas_digest == ORDERED_TOOL_SCHEMAS_SHA256
    assert config.per_attempt_cap_usd == PER_ATTEMPT_CAPS.midtier
    assert config.total_cap_usd == LIBRARY_RERUN_TOTAL_CAP_USD
    assert {ref.scenario for ref in config.scenario_qualifications} == {
        "addressing-runner",
        "agent-default-model",
        "context-usage-inbox",
        "export-credential",
        "gated-review-shortcuts",
        "native-compaction-summary",
        "operations-route",
        "restricted-evidence",
        "subject-only-build",
        "worker-silence-bound",
        "worker-start-budget",
    }
    for ref in config.scenario_qualifications:
        manifest = PILOT.parent / ref.scenario / "qualification/manifest.json"
        assert ref.manifest_digest == digest_bytes(manifest.read_bytes())
        qualified_image = json.loads(manifest.read_bytes())["observed_runtime_image_digest"]
        assert qualified_image == config.image_digest
    cohort = CohortRequest.model_validate_json((directory / "library-rerun.json").read_bytes())
    assert len(cohort.plans) == 1
    assert cohort.plans[0].config == Path("library-rerun-midtier.json")
    assert cohort.combined_cap_usd == config.total_cap_usd


def test_pilot_reuses_cell_table_shapes() -> None:
    from typing import get_args

    from code_extension.fact_shapes.cells import Shape
    from code_extension.fact_shapes.settings import FACT_SHAPES, PILOT_ALLOCATION

    assert get_args(Shape) == FACT_SHAPES
    assert {cell.shape for cell in PILOT_ALLOCATION} == set(get_args(Shape))
