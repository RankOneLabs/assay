from __future__ import annotations

import asyncio
import copy
import dataclasses
import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

import paa_contracts
import pytest
from jig.core.types import CompletionParams, LLMResponse, ToolCall, Usage

from assay.adapters.consistency import (
    ConsistencyWorker,
    DescribedClient,
    PilotSettings,
    render_input,
)
from assay.canonical import canonical_json
from assay.execution import EvaluationFailed, WorkerFailure, WorkerSuccess
from assay.investigations.consistency import TASKS, StructuralEvaluator
from assay.investigations.pilot import (
    PilotFailed,
    PilotPrepared,
    PilotSucceeded,
    installed_jig_revision,
    prepare_pilot,
    run_pilot,
)
from assay.models import EvaluationCoordinate
from assay.store import ObjectStore
from assay.verify import verify_bundle, verify_manifest


def realization() -> dict[str, Any]:
    return {
        "task": TASKS[0].model_dump(),
        "repository": {"module.py": TASKS[0].helper_source},
        "base_subject_ref": "sha256:" + "0" * 64,
    }


class FakeFactory:
    def __init__(self, mode: str = "offline") -> None:
        self.identity: dict[str, Any] = {
            "model": "fake-only",
            "endpoint": "memory://test",
            "revision": "1",
            "billing": mode,
            "hidden_retries": 0,
        }
        self.created = 0
        self.closed = 0
        self.calls: list[CompletionParams] = []
        self.source: Any = TASKS[0].reused_source
        self.error: Exception | None = None
        self.cost: float | None = 0
        self.block = False
        self.plain_text = False
        self.started = asyncio.Event()
        self.live_drift = False
        self.cleanup_error = False
        self.dynamic_source = False
        self.response_model: str | None = None

    def configuration(self) -> dict[str, Any]:
        return dict(self.identity)

    def create(self) -> DescribedClient:
        self.created += 1
        owner = self

        class Client(DescribedClient):
            def configuration(self) -> dict[str, Any]:
                return {**owner.identity, "model": "drift"} if owner.live_drift else owner.identity

            async def complete(self, params: CompletionParams) -> LLMResponse:
                owner.calls.append(copy.deepcopy(params))
                owner.started.set()
                if owner.block:
                    await asyncio.Event().wait()
                if owner.error:
                    raise owner.error
                source = owner.source
                if owner.dynamic_source:
                    value = json.loads(params.messages[0].content)
                    task = next(t for t in TASKS if t.instruction == value["instruction"])
                    source = task.reused_source
                return LLMResponse(
                    content="```python\nignored\n```" if owner.plain_text else "",
                    tool_calls=None
                    if owner.plain_text
                    else [
                        ToolCall("submission", "submit_output", {"source": source}),
                    ],
                    usage=Usage(10, 5, owner.cost),
                    latency_ms=1,
                    model=owner.response_model or owner.identity["model"],
                )

            async def aclose(self) -> None:
                owner.closed += 1
                if owner.cleanup_error:
                    raise RuntimeError("close failed")

        return Client()


@pytest.mark.asyncio
async def test_real_jig_runner_source_extraction_isolation_and_usage() -> None:
    factory = FakeFactory()
    settings = PilotSettings(temperature=0.25, max_output_tokens=1024)
    worker = ConsistencyWorker(factory, settings)
    declared = canonical_json(worker.configuration("clean"))
    first, second = await asyncio.gather(
        *(worker.run(input_value=realization(), arm_id=arm) for arm in ("clean", "inconsistent"))
    )
    for result in (first, second):
        assert isinstance(result, WorkerSuccess), result
        assert result.output == {"source": TASKS[0].reused_source}
        assert result.accounting.usage == {"llm_calls": 1, "input_tokens": 10, "output_tokens": 5}
        assert result.accounting.amount == 0
        assert result.trace["spans"]
        canonical_json(result.trace)
    assert first.trace["spans"][0]["trace_id"] != second.trace["spans"][0]["trace_id"]
    assert factory.created == factory.closed == 2
    assert canonical_json(worker.configuration("clean")) == declared
    assert declared == canonical_json(worker.configuration("inconsistent"))
    for params in factory.calls:
        assert len(params.messages) == 1
        assert params.temperature == 0.25 and params.max_tokens == 1024
        assert [tool.name for tool in params.tools or []] == ["submit_output"]
        prompt = json.loads(params.messages[0].content)
        assert set(prompt) == {"instruction", "repository"}
        assert "reused_source" not in params.messages[0].content
        assert "primitive" not in params.messages[0].content
        assert "primitives" not in params.messages[0].content


@pytest.mark.parametrize("mutation", ["path", "source", "instruction", "top", "oversize"])
@pytest.mark.asyncio
async def test_bad_inputs_fail_before_client_creation(mutation: str) -> None:
    value = realization()
    if mutation == "path":
        value["repository"] = {"../module.py": "bad"}
    elif mutation == "source":
        value["repository"]["module.py"] = 42
    elif mutation == "instruction":
        value["task"]["instruction"] = None
    elif mutation == "top":
        value["arm_id"] = "inconsistent"
    else:
        value["repository"]["module.py"] = "x" * 40_000
    factory = FakeFactory()
    result = await ConsistencyWorker(factory, PilotSettings()).run(
        input_value=value,
        arm_id="clean",
    )
    assert isinstance(result, WorkerFailure) and result.error_type == "InvalidInput"
    assert factory.created == 0


def test_rendering_is_deterministic_and_does_not_mutate_input() -> None:
    value = realization()
    original = copy.deepcopy(value)
    other = dict(reversed(list(value.items())))
    assert render_input(value, 10_000) == render_input(other, 10_000)
    assert value == original
    configuration = ConsistencyWorker(FakeFactory(), PilotSettings()).configuration("clean")
    assert configuration["rendering"] == "instruction-and-repository-map-canonical-json-v2"


@pytest.mark.parametrize(
    "plain,source", [(True, "ignored"), (False, 42), (False, ""), (False, "   ")]
)
@pytest.mark.asyncio
async def test_invalid_structured_output_retains_trace_and_accounting(
    plain: bool,
    source: Any,
) -> None:
    factory = FakeFactory()
    factory.plain_text, factory.source = plain, source
    result = await ConsistencyWorker(factory, PilotSettings()).run(
        input_value=realization(),
        arm_id="clean",
    )
    assert isinstance(result, WorkerFailure)
    assert result.trace["spans"] and result.accounting.usage["llm_calls"] >= 1
    assert factory.created == factory.closed == 1


@pytest.mark.asyncio
async def test_provider_exception_is_typed_and_halts_future_requests() -> None:
    factory = FakeFactory()
    factory.error = RuntimeError("transport failed")
    worker = ConsistencyWorker(factory, PilotSettings())
    result = await worker.run(input_value=realization(), arm_id="clean")
    assert isinstance(result, WorkerFailure) and result.error_type == "RuntimeError"
    assert result.accounting.usage == {"llm_calls": 1}
    assert result.trace["billing_uncertain"]
    factory.error = None
    again = await worker.run(input_value=realization(), arm_id="inconsistent")
    assert isinstance(again, WorkerFailure) and again.error_type == "BudgetHalted"
    assert len(factory.calls) == 1


@pytest.mark.parametrize("request_timeout,attempt_timeout", [(0.01, 1), (0.01, 0.01)])
@pytest.mark.asyncio
async def test_timeouts_cleanup_and_retained_reservations(
    request_timeout: float,
    attempt_timeout: float,
) -> None:
    factory = FakeFactory()
    factory.block = True
    worker = ConsistencyWorker(
        factory,
        PilotSettings(
            request_timeout_s=request_timeout,
            attempt_timeout_s=attempt_timeout,
        ),
    )
    result = await worker.run(input_value=realization(), arm_id="clean")
    assert isinstance(result, WorkerFailure) and result.error_type == "TimeoutError"
    assert factory.closed == 1 and result.trace["billing_uncertain"]
    assert result.accounting.usage == {"llm_calls": 1}


@pytest.mark.asyncio
async def test_external_cancellation_propagates_and_closes_client() -> None:
    factory = FakeFactory()
    factory.block = True
    worker = ConsistencyWorker(factory, PilotSettings())
    task = asyncio.create_task(worker.run(input_value=realization(), arm_id="clean"))
    await factory.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert factory.closed == 1
    again = await worker.run(input_value=realization(), arm_id="clean")
    assert isinstance(again, WorkerFailure) and again.error_type == "BudgetHalted"


@pytest.mark.parametrize("cancel_during_attempt", [False, True])
@pytest.mark.parametrize("close_outcome", ["success", "error", "timeout"])
@pytest.mark.asyncio
async def test_repeated_cancellation_drains_bounded_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    cancel_during_attempt: bool,
    close_outcome: str,
) -> None:
    factory = FakeFactory()
    factory.block = cancel_during_attempt
    close_started, close_release, close_finished = (asyncio.Event() for _ in range(3))
    close_tasks: list[asyncio.Task[Any]] = []
    create = factory.create

    def create_with_slow_close() -> DescribedClient:
        client = create()

        async def close() -> None:
            current = asyncio.current_task()
            assert current is not None
            close_tasks.append(current)
            close_started.set()
            try:
                await close_release.wait()
                if close_outcome == "error":
                    raise RuntimeError("close failed")
                factory.closed += 1
            finally:
                close_finished.set()

        monkeypatch.setattr(client, "aclose", close)
        return client

    monkeypatch.setattr(factory, "create", create_with_slow_close)
    worker = ConsistencyWorker(factory, PilotSettings(cleanup_timeout_s=0.1))
    task = asyncio.create_task(worker.run(input_value=realization(), arm_id="clean"))
    if cancel_during_attempt:
        await asyncio.wait_for(factory.started.wait(), 1)
        task.cancel()
    await asyncio.wait_for(close_started.wait(), 1)
    for _ in range(3):
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        assert not close_finished.is_set()
    if close_outcome != "timeout":
        close_release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert close_finished.is_set()
    assert len(close_tasks) == 1 and close_tasks[0].done()
    assert factory.closed == (1 if close_outcome == "success" else 0)


@pytest.mark.parametrize("provider_failure", [False, True])
@pytest.mark.asyncio
async def test_cleanup_timeout_is_drained_and_preserves_result_details(
    monkeypatch: pytest.MonkeyPatch,
    provider_failure: bool,
) -> None:
    factory = FakeFactory()
    if provider_failure:
        factory.error = RuntimeError("provider failed")
    close_finished = asyncio.Event()
    create = factory.create

    def create_with_stuck_close() -> DescribedClient:
        client = create()

        async def close() -> None:
            try:
                await asyncio.Event().wait()
            finally:
                close_finished.set()

        monkeypatch.setattr(client, "aclose", close)
        return client

    monkeypatch.setattr(factory, "create", create_with_stuck_close)
    result = await ConsistencyWorker(factory, PilotSettings(cleanup_timeout_s=0.01)).run(
        input_value=realization(),
        arm_id="clean",
    )
    assert close_finished.is_set()
    assert isinstance(result, WorkerFailure)
    assert result.error_type == ("RuntimeError" if provider_failure else "CleanupFailed")
    assert result.trace["cleanup_error"].startswith("TimeoutError:")
    assert result.accounting.usage["llm_calls"] == 1


@pytest.mark.asyncio
async def test_created_client_drift_fails_before_completion() -> None:
    factory = FakeFactory()
    factory.live_drift = True
    result = await ConsistencyWorker(factory, PilotSettings()).run(
        input_value=realization(),
        arm_id="clean",
    )
    assert isinstance(result, WorkerFailure) and "differs" in result.message
    assert not factory.calls and factory.closed == 1


@pytest.mark.asyncio
async def test_cleanup_failure_is_recorded() -> None:
    factory = FakeFactory()
    factory.cleanup_error = True
    result = await ConsistencyWorker(factory, PilotSettings()).run(
        input_value=realization(),
        arm_id="clean",
    )
    assert isinstance(result, WorkerFailure) and result.error_type == "CleanupFailed"
    assert result.trace["cleanup_error"] and result.accounting.usage["llm_calls"] == 1


def paid_settings(**overrides: Any) -> PilotSettings:
    return PilotSettings(
        mode="paid",
        max_spend_usd=Decimal("0.02"),
        request_cost_bound_usd=Decimal("0.01"),
        pricing_basis="test-maximum-request-charge",
        **overrides,
    )


@pytest.mark.asyncio
async def test_paid_requires_explicit_opt_in_without_creating_client() -> None:
    factory = FakeFactory("paid")
    result = await ConsistencyWorker(factory, paid_settings()).run(
        input_value=realization(),
        arm_id="clean",
    )
    assert isinstance(result, WorkerFailure) and result.error_type == "PaidExecutionDenied"
    assert factory.created == 0


@pytest.mark.parametrize("limit,expected", [(1, "RequestLimit"), (10, "SpendLimit")])
@pytest.mark.asyncio
async def test_concurrent_admission_reserves_before_calls(limit: int, expected: str) -> None:
    factory = FakeFactory("paid")
    factory.cost = 0.001
    worker = ConsistencyWorker(factory, paid_settings(max_total_requests=limit), allow_paid=True)
    results = await asyncio.gather(
        *(worker.run(input_value=realization(), arm_id="clean") for _ in range(4))
    )
    assert len(factory.calls) == min(limit, 2)
    assert all(
        isinstance(result, WorkerSuccess) or result.error_type == expected for result in results
    )


@pytest.mark.parametrize("cost", [None, 0.02, float("nan"), -1])
@pytest.mark.asyncio
async def test_unknown_invalid_or_overbound_cost_halts_paid_admission(cost: float | None) -> None:
    factory = FakeFactory("paid")
    factory.cost = cost
    worker = ConsistencyWorker(factory, paid_settings(), allow_paid=True)
    first = await worker.run(input_value=realization(), arm_id="clean")
    assert isinstance(first, WorkerFailure) and first.accounting.amount is None
    second = await worker.run(input_value=realization(), arm_id="clean")
    assert isinstance(second, WorkerFailure) and second.error_type == "BudgetHalted"
    assert len(factory.calls) == 1


@pytest.mark.parametrize(
    "expression",
    [
        "lambda: normalize_name(value)",
        "(normalize_name(x) for x in value)",
        "[normalize_name(x) for x in value]",
        "{normalize_name(x) for x in value}",
        "{x: normalize_name(x) for x in value}",
        "normalize_name(value) if value else value",
        "value and normalize_name(value)",
    ],
)
@pytest.mark.asyncio
async def test_deferred_or_conditional_structure_is_ambiguous(expression: str) -> None:
    result = await StructuralEvaluator().evaluate(
        input_value={"task": TASKS[0].model_dump()},
        output={"source": f"def implement(value):\n    return {expression}\n"},
        coordinate=EvaluationCoordinate(
            cell_id="s:clean:w0", evaluator_id="abstraction", evaluator_repeat=0
        ),
    )
    assert isinstance(result, EvaluationFailed) and result.error_type == "AmbiguousStructure"


def prepare(store: ObjectStore, factory: FakeFactory, settings: PilotSettings) -> PilotPrepared:
    result = prepare_pilot(
        store,
        factory=factory,
        settings=settings,
        schemas={
            name: paa_contracts.load_schema(name)
            for name in ("paa-task", "paa-evidence-record", "paa-operating-record")
        },
    )
    assert isinstance(result, PilotPrepared), result
    return result


@pytest.mark.asyncio
async def test_prepare_inspect_authorize_execute_export_real_runner(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "store")
    factory = FakeFactory()
    factory.dynamic_source = True
    prepared = prepare(store, factory, PilotSettings())
    assert factory.created == 0
    assert prepared.executions == prepared.evaluations == 12
    result = await run_pilot(
        store,
        plan_ref=prepared.plan_ref,
        authorization=prepared.plan_ref,
        factory=factory,
        export_destination=tmp_path / "bundle",
    )
    assert isinstance(result, PilotSucceeded), result
    assert len(factory.calls) == factory.created == factory.closed == 12
    assert verify_manifest(store, result.manifest_ref) == ()
    assert verify_bundle(ObjectStore(tmp_path / "bundle"), result.report_ref) == ()
    report = json.loads(store.read_bytes(result.report_ref))
    assert report["comparisons"][0]["n"] == 3
    assert report["comparisons"][0]["decision"] == "descriptive_only"


@pytest.mark.parametrize("drift", ["authorization", "provider", "paid"])
@pytest.mark.asyncio
async def test_pilot_preflight_refuses_without_provider_calls(tmp_path: Path, drift: str) -> None:
    store = ObjectStore(tmp_path)
    factory = FakeFactory("paid" if drift == "paid" else "offline")
    prepared = prepare(store, factory, paid_settings() if drift == "paid" else PilotSettings())
    if drift == "provider":
        factory.identity["model"] = "changed"
    result = await run_pilot(
        store,
        plan_ref=prepared.plan_ref,
        authorization="sha256:" + "0" * 64 if drift == "authorization" else prepared.plan_ref,
        factory=factory,
    )
    assert isinstance(result, PilotFailed), result
    assert factory.created == 0


@pytest.mark.parametrize(
    "settings",
    [
        {"max_total_requests": True},
        {"request_timeout_s": float("nan")},
        {"max_spend_usd": "1"},
        {"mode": "paid"},
        {"request_timeout_s": 80},
    ],
)
def test_invalid_policies(settings: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        PilotSettings(**settings)


@pytest.mark.parametrize("mode", ["offline", "paid"])
@pytest.mark.parametrize("basis", ["", " ", "\t\n"])
def test_blank_pricing_basis_rejected_in_all_modes(mode: str, basis: str) -> None:
    with pytest.raises(ValueError, match="pricing basis must be nonblank"):
        PilotSettings(
            mode=mode,
            pricing_basis=basis,
            max_spend_usd="1" if mode == "paid" else "0",
            request_cost_bound_usd="0.01" if mode == "paid" else "0",
        )


def jig_metadata(**overrides: Any) -> dict[str, Any]:
    return {
        "url": "https://github.com/RankOneLabs/jig.git",
        "vcs_info": {"vcs": "git", "commit_id": "a" * 40, "requested_revision": "a" * 40},
        **overrides,
    }


@pytest.mark.parametrize(
    "direct",
    [
        None,
        "{",
        "null",
        "[]",
        "{}",
        json.dumps(jig_metadata(dir_info={"editable": True})),
        json.dumps(jig_metadata(dir_info={"editable": False})),
        json.dumps(jig_metadata(archive_info={})),
        json.dumps(jig_metadata(vcs_info=None)),
        *(
            json.dumps(jig_metadata(vcs_info={**jig_metadata()["vcs_info"], **change}))
            for change in (
                {"vcs": "hg"},
                {"commit_id": "z" * 40},
                {"commit_id": 123},
                {"commit_id": "a" * 39},
                {"requested_revision": "main"},
                {"requested_revision": "v1.0"},
                {"requested_revision": None},
                {"requested_revision": "a" * 7},
                {"requested_revision": "b" * 40},
            )
        ),
    ],
)
def test_installed_jig_rejects_unpinned_or_invalid_metadata(direct: str | None) -> None:
    with patch("assay.investigations.pilot.distribution") as distribution:
        distribution.return_value.read_text.return_value = direct
        with pytest.raises(ValueError):
            installed_jig_revision()


@pytest.mark.parametrize("requested", ["a" * 40, "A" * 40])
def test_installed_jig_accepts_exact_commit_pin(requested: str) -> None:
    metadata = jig_metadata()
    metadata["vcs_info"]["requested_revision"] = requested
    with patch("assay.investigations.pilot.distribution") as distribution:
        distribution.return_value.read_text.return_value = json.dumps(metadata)
        assert installed_jig_revision() == "a" * 40
        distribution.assert_called_once_with("jig")
        distribution.return_value.read_text.assert_called_once_with("direct_url.json")


@pytest.mark.asyncio
async def test_unpinned_runtime_fails_prepare_and_run_before_provider_calls(tmp_path: Path) -> None:
    store, factory = ObjectStore(tmp_path), FakeFactory()
    prepared = prepare(store, factory, PilotSettings())
    metadata = jig_metadata()
    metadata["vcs_info"]["requested_revision"] = "main"
    with patch("assay.investigations.pilot.distribution") as distribution:
        distribution.return_value.read_text.return_value = json.dumps(metadata)
        failed_prepare = prepare_pilot(
            store,
            factory=factory,
            settings=PilotSettings(),
            schemas={
                name: paa_contracts.load_schema(name)
                for name in ("paa-task", "paa-evidence-record", "paa-operating-record")
            },
        )
        failed_run = await run_pilot(
            store,
            plan_ref=prepared.plan_ref,
            authorization=prepared.plan_ref,
            factory=factory,
        )
    for result in (failed_prepare, failed_run):
        assert isinstance(result, PilotFailed)
        assert result.error_type == "ValueError" and "exact full Git commit" in result.message
    assert factory.created == 0 and factory.calls == []


@pytest.mark.asyncio
async def test_run_pilot_reports_a_missing_legacy_extra_before_reading_jig_metadata(
    tmp_path: Path,
) -> None:
    """A Jig-free install must see the actionable assay[legacy] error, not a raw
    PackageNotFoundError from installed_jig_revision's importlib.metadata lookup.
    """
    store, factory = ObjectStore(tmp_path), FakeFactory()
    prepared = prepare(store, factory, PilotSettings())
    with (
        patch(
            "assay.investigations.pilot._import_legacy_worker_stack",
            side_effect=ModuleNotFoundError("assay[legacy]"),
        ),
        patch(
            "assay.investigations.pilot.installed_jig_revision",
            side_effect=AssertionError("installed_jig_revision must not run first"),
        ),
    ):
        result = await run_pilot(
            store,
            plan_ref=prepared.plan_ref,
            authorization=prepared.plan_ref,
            factory=factory,
        )
    assert isinstance(result, PilotFailed)
    assert result.error_type == "ModuleNotFoundError" and "assay[legacy]" in result.message


def test_worker_policy_cannot_diverge_from_ledger() -> None:
    worker = ConsistencyWorker(FakeFactory(), PilotSettings())
    with pytest.raises(dataclasses.FrozenInstanceError):
        worker.settings = PilotSettings(max_total_requests=1)


@pytest.mark.asyncio
async def test_response_model_drift_preserves_provider_details() -> None:
    factory = FakeFactory()
    factory.response_model = "different-model"
    result = await ConsistencyWorker(factory, PilotSettings()).run(
        input_value=realization(),
        arm_id="clean",
    )
    assert isinstance(result, WorkerFailure) and "model differs" in result.message
    assert result.trace["response_models"] == ["different-model"]
    assert result.trace["provider_usage"][0]["input_tokens"] == 10


@pytest.mark.parametrize(
    ("source", "error_type"),
    [
        ("def implement(value=normalize_name('default')):\n    return value\n", "InvalidOutput"),
        (
            "@normalize_name('decorator')\ndef implement(value):\n    return value\n",
            "InvalidOutput",
        ),
        ("def implement(value):\n    return\n", "AmbiguousStructure"),
    ],
)
@pytest.mark.asyncio
async def test_calls_outside_return_expression_are_not_reuse(
    source: str, error_type: str
) -> None:
    result = await StructuralEvaluator().evaluate(
        input_value={"task": TASKS[0].model_dump()},
        output={"source": source},
        coordinate=EvaluationCoordinate(
            cell_id="s:clean:w0", evaluator_id="abstraction", evaluator_repeat=0
        ),
    )
    assert isinstance(result, EvaluationFailed) and result.error_type == error_type


@pytest.mark.parametrize("failure", ["provider", "ambiguous", "export"])
@pytest.mark.asyncio
async def test_pilot_missingness_and_post_execution_failure_refs(
    tmp_path: Path,
    failure: str,
) -> None:
    store = ObjectStore(tmp_path / "store")
    factory = FakeFactory()
    factory.dynamic_source = failure == "export"
    if failure == "provider":
        factory.error = RuntimeError("provider unavailable")
    elif failure == "ambiguous":
        factory.source = "def implement(value): return value"
    prepared = prepare(store, factory, PilotSettings())
    destination = tmp_path / "export"
    if failure == "export":
        destination.mkdir()
        (destination / "keep.txt").write_text("existing user data")
    result = await run_pilot(
        store,
        plan_ref=prepared.plan_ref,
        authorization=prepared.plan_ref,
        factory=factory,
        export_destination=destination,
    )
    assert result.manifest_ref is not None
    # A provider failure fails every worker, so every planned evaluation is
    # genuinely unavailable and the manifest is honestly incomplete; the
    # other failure modes leave the worker succeeding, so their manifest
    # stays complete and verification is clean.
    expected_codes = ["incomplete_run"] if failure == "provider" else []
    assert [f.code for f in verify_manifest(store, result.manifest_ref)] == expected_codes
    if failure == "export":
        assert isinstance(result, PilotFailed) and result.report_ref is not None
        assert (destination / "keep.txt").read_text() == "existing user data"
    else:
        assert isinstance(result, PilotSucceeded), result
        assert verify_bundle(ObjectStore(destination), result.report_ref) == ()
        report = json.loads(store.read_bytes(result.report_ref))
        assert report["comparisons"][0]["n"] == 0
        key = "execution_failures" if failure == "provider" else "evaluation_failures"
        assert report["missingness"]["clean"][key] == 6


@pytest.mark.asyncio
async def test_paid_policy_full_pipeline_with_fake_provider_only(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "store")
    factory = FakeFactory("paid")
    factory.dynamic_source, factory.cost = True, 0.001
    settings = PilotSettings(
        mode="paid",
        max_spend_usd="0.24",
        request_cost_bound_usd="0.01",
        pricing_basis="test-only-bound",
    )
    prepared = prepare(store, factory, settings)
    result = await run_pilot(
        store,
        plan_ref=prepared.plan_ref,
        authorization=prepared.plan_ref,
        factory=factory,
        allow_paid=True,
        export_destination=tmp_path / "bundle",
    )
    assert isinstance(result, PilotSucceeded), result
    assert verify_bundle(ObjectStore(tmp_path / "bundle"), result.report_ref) == ()
    manifest = json.loads(store.read_bytes(result.manifest_ref))
    records = [
        json.loads(store.read_bytes(ref))
        for key, ref in manifest["operating_records"].items()
        if key.startswith("worker:")
    ]
    assert len(records) == 12
    assert all(record["price"]["amount"] == 0.001 for record in records)
