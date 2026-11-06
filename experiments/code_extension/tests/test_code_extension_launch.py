"""A cohort runs its plans in order, stops at a halt, and reports where it stands."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from code_extension import launch as cohort
from code_extension import run
from code_extension.archive import AttemptArchive
from code_extension.budget import AttemptJournal
from code_extension.config import RunConfiguration
from code_extension.fixture import ADDED_SCENARIOS, PILOT, materialize, read_tree
from code_extension.fixtures import load_scenario
from code_extension.probe import SUBMIT
from code_extension.resume import resume
from code_extension.status import plan_state, plan_status, store_status
from code_extension.tests.test_code_extension_hosted import hosted_configuration
from workflow_edit.tests.test_workflow_edit_bridge import FakeSandbox

from assay.canonical import digest_bytes
from assay.investigations.workflow_correctness import (
    GroupResult,
    PreflightResult,
    WorkflowCorrectnessResult,
)
from assay.models import CellCoordinate, ExecutionOutcome, RunManifest
from assay.store import ObjectStore

pytestmark = pytest.mark.usefixtures("qualified_runner")

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
SCENARIO = "stage-pass-through"
CAP = Decimal("2.00")


def cell_id(task: dict[str, Any]) -> str:
    return CellCoordinate.model_validate(task).id


def study_configuration(seed: int) -> RunConfiguration:
    """One arm set, one repeat: four attempts in a stated plan order."""
    manifest = PILOT.parent / SCENARIO / "qualification" / "manifest.json"
    return RunConfiguration.model_validate({
        **hosted_configuration().model_dump(mode="json"), "repeats": 1,
        "randomization_seed": seed, "total_cap_usd": str(CAP),
        "scenario_qualifications": [{"scenario": SCENARIO,
                                     "manifest_digest": digest_bytes(manifest.read_bytes())}],
        "image_digest": json.loads(manifest.read_bytes())["observed_runtime_image_digest"],
    })


@dataclass
class Provider:
    """A scripted hosted route that writes the reference answer, then submits."""

    root: Path
    requests: Counter[str] = field(default_factory=Counter)
    order: list[str] = field(default_factory=list)
    before_request: Callable[[str], None] | None = None
    fail_on: set[tuple[str, int]] = field(default_factory=set)
    scripts: dict[str, list[tuple[str, dict[str, Any]]]] = field(default_factory=dict)

    def script(self, coordinate: str, attempt: str) -> list[tuple[str, dict[str, Any]]]:
        if attempt not in self.scripts:
            subject, arm, _ = coordinate.rsplit(":", 2)
            assert subject.endswith(SCENARIO)
            fixture = load_scenario(SCENARIO, arm_id=arm)
            target = self.root / "reference" / attempt.replace(":", "-")
            materialize(target, fixture.repository, fixture.arms[0].reference_patch)
            patched = read_tree(target)
            changed = sorted(p for p in patched if patched[p] != fixture.repository.get(p))
            self.scripts[attempt] = [
                *(("write_file", {"path": p, "content": patched[p]}) for p in changed),
                ("submit_output", SUBMIT),
            ]
        return self.scripts[attempt]

    def client(self, agent: Any) -> httpx.Client:
        from assay_pier_bridge.agent_loop import InFlightDeadline

        def respond(_request: httpx.Request) -> httpx.Response:
            coordinate = agent.coordinate
            self.requests[coordinate] += 1
            if coordinate == "__route_probe__":
                message: dict[str, Any] = {"role": "assistant", "content": "OK"}
                reason = "stop"
            else:
                if coordinate not in self.order:
                    self.order.append(coordinate)
                if self.before_request is not None:
                    self.before_request(coordinate)
                if (coordinate, self.requests[coordinate]) in self.fail_on:
                    raise InFlightDeadline(bytes_received=False)
                name, arguments = self.script(coordinate, agent.cell_key).pop(0)
                message = {"role": "assistant", "content": None, "tool_calls": [{
                    "id": name, "type": "function", "function": {
                        "name": name, "arguments": json.dumps(arguments),
                    },
                }]}
                reason = "tool_calls"
            return httpx.Response(200, json={
                "model": agent.paid_turn_route.model, "provider": "Azure",
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.001},
                "choices": [{"message": message, "finish_reason": reason}],
            })

        return httpx.Client(transport=httpx.MockTransport(respond))


@pytest.fixture
def provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Provider:
    scripted = Provider(tmp_path)

    async def joined(function: Any, *args: Any, **kwargs: Any) -> Any:
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(function, *args, **kwargs).result()

    async def grade(_self: Any, **kwargs: Any) -> WorkflowCorrectnessResult:
        return WorkflowCorrectnessResult(
            "correct", tuple(GroupResult(g.name, "passed") for g in kwargs["groups"]),
            preflight=PreflightResult("passed"),
        )

    def sandbox(*args: Any, **kwargs: Any) -> FakeSandbox:
        kwargs.pop("limits", None)
        return FakeSandbox(*args, **kwargs)

    image = study_configuration(1).image_digest
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("CODE_EXTENSION_ROUTING_CONFIG", raising=False)
    monkeypatch.setattr("code_extension.bridge.observed_image_digest", lambda _: image)
    monkeypatch.setattr("assay_pier_bridge.agent_loop.RepositoryAgentClient._http_client",
                        lambda agent: scripted.client(agent))
    monkeypatch.setattr("code_extension.bridge.DockerTmpfsToolSandbox", sandbox)
    monkeypatch.setattr("code_extension.run.asyncio.to_thread", joined)
    monkeypatch.setattr("code_extension.run.DockerWorkflowRunner.run", grade)
    return scripted


def write_request(root: Path, *, combined: str = "4.00") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name, seed in (("first", 1), ("second", 2)):
        (root / f"{name}.json").write_bytes(study_configuration(seed).canonical_bytes())
    path = root / "cohort-request.json"
    path.write_text(json.dumps({
        "cohort": "launch-test", "combined_cap_usd": combined,
        "plans": [{"name": "first", "config": "first.json"},
                  {"name": "second", "config": "second.json"}],
    }))
    return path


def tree_digest(root: Path) -> str:
    entries = sorted(
        (str(path.relative_to(root)), hashlib.sha256(path.read_bytes()).hexdigest())
        for path in root.rglob("*") if path.is_file()
    )
    return json.dumps(entries)


@pytest.mark.asyncio
async def test_cohort_runs_in_order_and_a_second_launch_dispatches_nothing(
    tmp_path: Path, provider: Provider,
) -> None:
    store = tmp_path / "store"
    summary = cohort.prepare_cohort(write_request(tmp_path / "request"), store)
    assert summary["attempts"] == 8
    assert summary["caps"]["combined_usd"] == "4.00"
    assert summary["caps"]["plan_total_usd"] == "4.00"
    assert provider.requests == Counter()
    first, second = (plan["digest"] for plan in summary["plans"])
    observed: list[dict[str, Any]] = []

    def watch(coordinate: str) -> None:
        if provider.order.index(coordinate) == 1 and provider.requests[coordinate] == 1:
            observed.append(plan_status(ObjectStore(store), first))

    provider.before_request = watch
    result = await cohort.launch(Path(summary["cohort"]), summary["digest"], store)
    assert result["status"] == "finished"
    assert [plan["name"] for plan in result["plans"]] == ["first", "second"]
    assert provider.requests["__route_probe__"] == 2

    # The plan was read mid-grid, before anything had settled.
    live = observed[0]
    assert live["state"] == "in_progress"
    assert (live["started"], live["terminal"], live["completed_normally"]) == (2, 1, 1)
    assert live["active_coordinate"] == provider.order[1]
    assert live["evaluated"] is None and live["passed"] is None
    assert live["unstarted"] == 2 and live["last_activity"] is not None
    assert live["unsettled_requests"] != []

    status = store_status(store, cohort=summary["digest"])
    assert status["state"] == "finished"
    assert [plan["name"] for plan in status["plans"]] == ["first", "second"]
    assert all(status[name] == 8 for name in (
        "planned", "started", "terminal", "completed_normally", "evaluated", "passed",
    ))
    assert status["unstarted"] == 0 and status["unknown_charges"] == []
    assert status["measured_usd"] == status["conservative_usd"]
    assert Decimal(status["measured_usd"]) == Decimal("0.001") * sum(provider.requests.values())

    before = dict(provider.requests)
    again = await cohort.launch(Path(summary["cohort"]), summary["digest"], store)
    assert again == {"status": "finished", "cohort": summary["digest"], "plans": []}
    assert dict(provider.requests) == before
    assert second != first


@pytest.mark.asyncio
async def test_archive_records_each_attempts_position_seed_and_own_end_time(
    tmp_path: Path, provider: Provider,
) -> None:
    store_path = tmp_path / "store"
    config = study_configuration(7)
    path = tmp_path / "config.json"
    path.write_bytes(config.canonical_bytes())
    summary = run.prepare(path, store_path)
    result = await run.execute(Path(summary["plan"]), summary["digest"], store_path)
    assert result["status"] == "RunSucceeded"
    directory = Path(result["archive"])
    archive = AttemptArchive.open_existing(directory.name, directory.parent)
    store = ObjectStore(store_path)
    manifest = RunManifest.model_validate_json(
        store.read_bytes(json.loads(Path(result["run_index"]).read_bytes())["manifest_ref"])
    )
    cells = [cell_id(cell) for cell in summary["tasks"]]
    assert provider.order == cells
    for position, cell in enumerate(cells):
        record = archive.read(cell)
        assert record.schedule_order == position and record.schedule_seed == 7
        outcome = ExecutionOutcome.model_validate_json(
            store.read_bytes(manifest.execution_records[cell])
        )
        assert record.completed_at == outcome.completed_at
    ends = [archive.read(cell).completed_at for cell in cells]
    assert len(set(ends)) == len(cells), "attempts must not share one batch time"


@pytest.mark.asyncio
async def test_a_halt_stops_the_cohort_until_resume_clears_that_plan(
    tmp_path: Path, provider: Provider,
) -> None:
    store = tmp_path / "store"
    summary = cohort.prepare_cohort(write_request(tmp_path / "request"), store)
    first, second = summary["plans"]
    victim = cell_id(first["tasks"][1])
    provider.fail_on.add((victim, 1))
    halted = await cohort.launch(Path(summary["cohort"]), summary["digest"], store)
    assert halted["status"] == "halted" and len(halted["plans"]) == 1

    status = store_status(store, cohort=summary["digest"])
    plan, untouched = status["plans"]
    assert status["state"] == "halted"
    assert plan["state"] == "halted" and plan["halt_reason"] == "billing_uncertain"
    assert (plan["started"], plan["unstarted"]) == (2, 2)
    assert len(plan["unknown_charges"]) == 1
    assert Decimal(plan["conservative_usd"]) > Decimal(plan["measured_usd"])
    assert plan["evaluated"] == 1 and plan["manifest_ref"] is not None
    assert untouched["state"] == "prepared" and untouched["started"] == 0
    assert not (Path(second["plan"]).parent / "attempts.jsonl").exists()

    with pytest.raises(run.LaunchRefused, match="first is halted"):
        await cohort.launch(Path(summary["cohort"]), summary["digest"], store)
    assert not (Path(second["plan"]).parent / "attempts.jsonl").exists()

    # The halted manifest holds a spending refusal for the next cell. Once that
    # cell really runs, status must describe the attempt and not the refusal.
    refused = cell_id(first["tasks"][2])
    during: list[dict[str, Any]] = []

    def watch(coordinate: str) -> None:
        if coordinate == refused and not during:
            during.append(plan_status(ObjectStore(store), first["digest"]))

    provider.before_request = watch
    index = Path(halted["plans"][0]["run_index"])
    replaced = index.stat().st_ino
    resumed = await resume(
        Path(first["plan"]), first["digest"], store, plan["manifest_ref"],
        accept_unknown="Operator accepted the full reservation",
    )
    assert resumed["status"] == "RunSucceeded"
    assert during[0]["active_coordinate"] == refused
    assert (during[0]["started"], during[0]["terminal"]) == (3, 2)
    assert index.stat().st_ino != replaced, "a reader must never see run.json half written"
    assert plan_status(ObjectStore(store), first["digest"])["completed_normally"] == 3
    finished = await cohort.launch(Path(summary["cohort"]), summary["digest"], store)
    assert [item["name"] for item in finished["plans"]] == ["second"]
    assert finished["status"] == "finished"

    final = store_status(store, cohort=summary["digest"])
    assert final["state"] == "finished" and final["terminal"] == 8
    # The failed attempt stays failed and unreplaced; its charge stays unknown.
    assert final["completed_normally"] == 7
    journal = (Path(first["plan"]).parent / "attempts.jsonl").read_bytes().splitlines()
    claims = [json.loads(line) for line in journal]
    assert sum(r["event"] == "attempt_started" and r["coordinate"] == victim for r in claims) == 1
    assert len(final["unknown_charges"]) == 1
    assert Decimal(final["conservative_usd"]) <= Decimal("4.00")


@pytest.mark.asyncio
async def test_preflight_checks_every_plan_before_the_first_request(
    tmp_path: Path, provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / "store"
    summary = cohort.prepare_cohort(write_request(tmp_path / "request"), store)
    path = Path(summary["cohort"])
    with pytest.raises(run.LaunchRefused, match="cohort_authorization_mismatch"):
        await cohort.launch(path, "sha256:" + "0" * 64, store)
    copied = tmp_path / "cohort.json"
    copied.write_bytes(path.read_bytes())
    with pytest.raises(run.LaunchRefused, match="original frozen cohort"):
        await cohort.launch(copied, summary["digest"], store)
    monkeypatch.delenv("OPENROUTER_API_KEY")
    with pytest.raises(run.LaunchRefused, match="OPENROUTER_API_KEY"):
        await cohort.launch(path, summary["digest"], store)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    plan = Path(summary["plans"][1]["plan"])
    plan.write_bytes(plan.read_bytes() + b" ")
    with pytest.raises(run.LaunchRefused, match="second: frozen plan artifact changed"):
        await cohort.launch(path, summary["digest"], store)
    assert provider.requests == Counter()
    assert not (Path(summary["plans"][0]["plan"]).parent / "attempts.jsonl").exists()


@pytest.mark.asyncio
async def test_a_second_launcher_is_refused_while_the_first_runs(
    tmp_path: Path, provider: Provider,
) -> None:
    store = tmp_path / "store"
    summary = cohort.prepare_cohort(write_request(tmp_path / "request"), store)
    first = Path(summary["plans"][0]["plan"])
    with run._plan_lock(first.parent), \
            pytest.raises(run.LaunchRefused, match="another process is running this plan"):
        await cohort.launch(Path(summary["cohort"]), summary["digest"], store)
    assert provider.requests == Counter()


@pytest.mark.asyncio
async def test_cohorts_sharing_a_plan_cannot_both_run_it(
    tmp_path: Path, provider: Provider,
) -> None:
    store = tmp_path / "store"
    request = write_request(tmp_path / "request")
    both = cohort.prepare_cohort(request, store)
    only = request.with_name("only-first.json")
    only.write_text(json.dumps({
        "cohort": "shares-first", "combined_cap_usd": "2.00",
        "plans": [{"name": "first", "config": "first.json"}],
    }))
    other = cohort.prepare_cohort(only, store)
    shared = both["plans"][0]
    assert other["plans"][0]["digest"] == shared["digest"]

    with run._plan_lock(Path(shared["plan"]).parent), \
            pytest.raises(run.LaunchRefused, match="another process is running this plan"):
        await cohort.launch(Path(other["cohort"]), other["digest"], store)
    with run._plan_lock(Path(shared["plan"]).parent), \
            pytest.raises(run.LaunchRefused, match="another process is running this plan"):
        await resume(Path(shared["plan"]), shared["digest"], store, "sha256:" + "0" * 64)
    assert provider.requests == Counter()

    # A launcher that passed preflight before the other run began still stops here.
    await cohort.launch(Path(both["cohort"]), both["digest"], store)
    before = dict(provider.requests)
    with pytest.raises(run.LaunchRefused, match="plan has already started"):
        await run.execute(Path(shared["plan"]), shared["digest"], store, unstarted_only=True)
    assert dict(provider.requests) == before


def test_plan_caps_must_fit_the_combined_cap(tmp_path: Path, provider: Provider) -> None:
    request = write_request(tmp_path / "request", combined="3.99")
    with pytest.raises(run.LaunchRefused, match="combined_cap_exceeded: plan caps total 4.00"):
        cohort.prepare_cohort(request, tmp_path / "store")
    assert not (tmp_path / "store").exists()
    assert provider.requests == Counter()


@pytest.mark.parametrize("change", [
    {"combined_cap_usd": "0"}, {"combined_cap_usd": "NaN"},
    {"plans": [{"name": "same", "config": "first.json"},
               {"name": "same", "config": "second.json"}]},
    {"plans": [{"name": "one", "config": "first.json"},
               {"name": "two", "config": "first.json"}]},
])
def test_a_malformed_cohort_is_refused(
    change: dict[str, Any], tmp_path: Path, provider: Provider,
) -> None:
    request = write_request(tmp_path / "request")
    request.write_text(json.dumps({**json.loads(request.read_text()), **change}))
    with pytest.raises(ValueError):
        cohort.prepare_cohort(request, tmp_path / "store")


def test_example_cohort_prepares_eighty_attempts_under_one_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = RunConfiguration.load(EXAMPLES / "hosted-matched-tasks-qwen.json").image_digest
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("CODE_EXTENSION_ROUTING_CONFIG", raising=False)
    monkeypatch.setattr("code_extension.bridge.observed_image_digest", lambda _: image)
    summary = cohort.prepare_cohort(EXAMPLES / "hosted-matched-tasks.json", tmp_path / "store")
    assert summary["attempts"] == 80 and summary["route_probe_calls"] == 2
    assert summary["caps"]["combined_usd"] == "16.00"
    assert summary["expected_serial_duration"]["maximum_seconds"] == 80 * 900
    assert [plan["attempts"] for plan in summary["plans"]] == [40, 40]
    assert {cell["subject_id"] for plan in summary["plans"] for cell in plan["tasks"]} == {
        ADDED_SCENARIOS[name].subject_id
        for name in ("stage-status-report", "stage-collect-artifacts")
    }
    assert (Path(summary["cohort"]).parent / "launch-summary.json").is_file()
    status = store_status(tmp_path / "store", cohort=summary["digest"])
    assert status["state"] == "prepared"
    assert status["planned"] == status["unstarted"] == 80 and status["started"] == 0


def test_status_counts_a_dead_runs_open_request_in_full_and_writes_nothing(
    tmp_path: Path, provider: Provider,
) -> None:
    store = tmp_path / "store"
    config = study_configuration(1)
    path = tmp_path / "config.json"
    path.write_bytes(config.canonical_bytes())
    summary = run.prepare(path, store)
    directory = Path(summary["plan"]).parent
    journal = AttemptJournal(directory / "attempts.jsonl", summary["digest"], config.digest())
    cell = cell_id(summary["tasks"][0])
    journal.record_run_started()
    journal.claim_attempt(cell, "attempt")
    journal.begin(cell, "attempt:request-1", Decimal("0.25"))
    journal.finish("attempt:request-1", cost=Decimal("0.01"), status="settled")
    journal.begin(cell, "attempt:request-2", Decimal("0.25"))
    journal.finish("attempt:request-2", cost=Decimal(0), status="not_sent")
    journal.begin(cell, "attempt:request-3", Decimal("0.25"))
    before = tree_digest(store)
    status = store_status(store)
    assert tree_digest(store) == before
    plan = status["plans"][0]
    assert plan["state"] == "in_progress" and plan["active_coordinate"] == cell
    assert Decimal(plan["measured_usd"]) == Decimal("0.01")
    assert Decimal(plan["conservative_usd"]) == Decimal("0.26")
    assert plan["unsettled_requests"] == ["attempt:request-3"] and plan["unknown_charges"] == []


@pytest.mark.parametrize(("events", "state"), [
    ([], "prepared"),
    ([{"event": "attempt_started"}], "unrecorded"),
    ([{"event": "run_started"}], "in_progress"),
    ([{"event": "run_started"},
      {"event": "run_ended", "result": "RunSucceeded", "halt": None}], "finished"),
    ([{"event": "run_started"},
      {"event": "run_ended", "result": "RunSucceeded", "halt": "billing_uncertain"}], "halted"),
    ([{"event": "run_started"},
      {"event": "run_ended", "result": "RunFailed", "halt": None}], "halted"),
    ([{"event": "run_started"},
      {"event": "run_ended", "result": "LaunchRefused", "halt": None}], "halted"),
    ([{"event": "run_ended", "result": "RunFailed", "halt": "billing_uncertain"},
      {"event": "run_started"}], "in_progress"),
])
def test_a_plans_state_is_its_last_run_event(events: list[dict[str, Any]], state: str) -> None:
    assert plan_state(events) == state


@pytest.mark.asyncio
async def test_a_failed_route_probe_ends_the_run_with_its_reason(
    tmp_path: Path, provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def refuse(*_args: Any) -> None:
        raise run.LaunchRefused("route_probe_failed: provider_error")

    monkeypatch.setattr("code_extension.run._route_probe", refuse)
    store = tmp_path / "store"
    summary = cohort.prepare_cohort(write_request(tmp_path / "request"), store)
    with pytest.raises(run.LaunchRefused, match="route_probe_failed"):
        await cohort.launch(Path(summary["cohort"]), summary["digest"], store)
    first, second = store_status(store, cohort=summary["digest"])["plans"]
    assert first["state"] == "halted"
    assert first["halt_reason"] == "LaunchRefused: route_probe_failed: provider_error"
    assert second["state"] == "prepared"
