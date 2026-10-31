"""Operator configuration and command surface checks."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from code_extension.budget import AttemptJournal
from code_extension.config import RunConfiguration
from code_extension.fixture import PILOT
from code_extension.fixtures import ScenarioFixture
from code_extension.probe import _scripted_client
from code_extension.protocol import ORDERED_TOOL_SCHEMAS_SHA256, SYSTEM_PROMPT_SHA256
from code_extension.run import (
    ExtensionStudyWorker,
    LaunchRefused,
    _build,
    _route_probe,
    execute,
    main,
    prepare,
)
from code_extension.settings import ExtensionAgentSettings
from code_extension.study import PreparedStudy, load_qualified_study_fixture
from verification_pilot.budget import SpendGate

from assay.canonical import digest_bytes
from assay.fixture_manifest import FixtureManifestV3
from assay.models import CellCoordinate
from assay.store import ObjectStore


def configuration() -> dict[str, object]:
    return {
        "scenario_qualifications": (
            {"scenario": "dispatch-handler", "manifest_digest": "sha256:" + "a" * 64},
        ),
        "cohort": "calibration",
        "route": {
            "endpoint": "http://willie:8900",
            "model": "qwen-coder-32b",
            "provider": "smithers-local",
        },
        "profile": "mcbain",
        "system_prompt_digest": SYSTEM_PROMPT_SHA256,
        "tool_schemas_digest": ORDERED_TOOL_SCHEMAS_SHA256,
        "image_digest": "sha256:" + "a" * 64,
        "bounds": ExtensionAgentSettings.for_model("qwen-coder-32b").model_dump(),
        "repeats": 1,
        "randomization_seed": 43,
        "concurrency": 1,
        "pricing": {"basis": None, "conservative_request_bound_usd": Decimal("0.01")},
        "per_attempt_cap_usd": Decimal("0.25"),
        "total_cap_usd": Decimal("1.00"),
    }


def forbid_model_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("pre-dispatch path constructed a provider client or turn completion")

    monkeypatch.setattr("assay.adapters.smithers.SmithersFactory.create", forbidden)
    monkeypatch.setattr("code_extension.run.SmithersTurnCompletion", forbidden)


def test_configuration_round_trip_and_required_fields() -> None:
    config = RunConfiguration.model_validate(configuration())
    assert RunConfiguration.model_validate_json(config.canonical_bytes()) == config
    assert config.digest() == digest_bytes(config.canonical_bytes())
    for field in ("route", "profile", "image_digest", "per_attempt_cap_usd", "total_cap_usd"):
        changed = configuration()
        changed.pop(field)
        with pytest.raises(ValueError):
            RunConfiguration.model_validate(changed)


def test_configuration_named_refusals() -> None:
    bad = configuration()
    bad["route"] = {
        "endpoint": "http://elsewhere",
        "model": "qwen-coder-32b",
        "provider": "smithers-local",
    }
    with pytest.raises(ValueError, match="unauthorized extension model route"):
        RunConfiguration.model_validate(bad)
    bad = configuration()
    bad["pricing"] = {"basis": None, "conservative_request_bound_usd": None}
    with pytest.raises(ValueError, match="pricing basis or conservative"):
        RunConfiguration.model_validate(bad)
    bad = configuration()
    bad["total_cap_usd"] = Decimal(0)
    with pytest.raises(ValueError, match="positive per-attempt and total"):
        RunConfiguration.model_validate(bad)
    bad = configuration()
    bad["system_prompt_digest"] = "sha256:" + "b" * 64
    with pytest.raises(ValueError, match="prompt or tool identity"):
        RunConfiguration.model_validate(bad)
    bad = configuration()
    bad["api_key"] = "sk-example"
    with pytest.raises(ValueError, match="secret field"):
        RunConfiguration.model_validate(bad)


def test_qualify_command_delegates_existing_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    forbid_model_dispatch(monkeypatch)
    seen: list[str] = []
    manifest_path = PILOT.parent / "dispatch-handler" / "qualification" / "manifest.json"
    manifest = FixtureManifestV3.model_validate_json(manifest_path.read_bytes())

    async def qualified(*, image: str, **_kwargs: object) -> FixtureManifestV3:
        seen.append(image)
        return manifest

    monkeypatch.setattr("code_extension.qualify.qualify", qualified)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run", "qualify", "--scenario", "dispatch-handler", "--image",
            manifest.observed_runtime_image_digest, "--verify-committed",
        ],
    )
    main()
    assert seen == [manifest.observed_runtime_image_digest]
    assert sys.argv[0] == "code_extension.qualify"
    assert sys.argv[-1] == "--verify-committed"


def test_scripted_command_is_model_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    forbid_model_dispatch(monkeypatch)
    calls: list[str] = []

    async def scripted(
        fixture: ScenarioFixture, manifest: FixtureManifestV3, image: str
    ) -> dict[str, str]:
        client = _scripted_client(fixture, manifest, image, tmp_path, [])
        assert type(client.factory).__name__ == "_NoModelFactory"
        calls.append(image)
        return {"independent_evaluator_verdict": "correct"}

    manifest = PILOT.parent / "dispatch-handler" / "qualification" / "manifest.json"
    image = json.loads(manifest.read_bytes())["observed_runtime_image_digest"]
    monkeypatch.setattr("code_extension.probe.reference_submission", scripted)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run", "scripted", "--scenario", "dispatch-handler", "--image", image,
            "--store", str(tmp_path / "store"),
        ],
    )
    main()
    assert calls == [image]


@pytest.mark.parametrize(
    "module", ["code_extension.run", "code_extension.qualify", "code_extension.diagnose"]
)
def test_existing_and_new_module_surfaces_accept_help(module: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", module, "--help"], capture_output=True, text=True, check=True
    )
    assert "usage:" in completed.stdout


def test_prepare_is_deterministic_and_model_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = PILOT.parent / "dispatch-handler" / "qualification" / "manifest.json"
    data = json.loads(manifest.read_bytes())
    value = configuration()
    value["scenario_qualifications"] = (
        {
            "scenario": "dispatch-handler",
            "manifest_digest": digest_bytes(manifest.read_bytes()),
        },
    )
    value["image_digest"] = data["observed_runtime_image_digest"]
    config = RunConfiguration.model_validate(value)
    config_path = tmp_path / "config.json"
    config_path.write_bytes(config.canonical_bytes())
    routing = tmp_path / "routing.yaml"
    routing.write_text(
        "machines:\n  mcbain:\n    backend: ollama\n"
        "models:\n  qwen-coder-32b:\n    machines: [mcbain]\n"
        "    ollama_tag: qwen-coder-32b\n"
    )
    monkeypatch.setenv("CODE_EXTENSION_ROUTING_CONFIG", str(routing))
    monkeypatch.setattr(
        "code_extension.bridge.observed_image_digest", lambda _image: config.image_digest
    )
    forbid_model_dispatch(monkeypatch)
    first = prepare(config_path, tmp_path / "store")
    second = prepare(config_path, tmp_path / "store")
    assert first["digest"] == second["digest"]
    assert Path(first["plan"]).read_bytes() == Path(second["plan"]).read_bytes()
    assert first["attempts"] == 1
    noncanonical = tmp_path / "noncanonical.json"
    noncanonical.write_text(
        json.dumps(json.loads(Path(first["plan"]).read_bytes()), indent=2)
    )
    with pytest.raises(ValueError, match="canonical wire JSON"):
        asyncio.run(
            execute(noncanonical, digest_bytes(noncanonical.read_bytes()), tmp_path / "store")
        )


def test_prepare_refuses_missing_scripted_gate_and_fixture_drift(tmp_path: Path) -> None:
    pilot = PILOT / "qualification" / "manifest.json"
    image = json.loads(pilot.read_bytes())["observed_runtime_image_digest"]
    with pytest.raises(ValueError, match="scripted full path qualification is absent"):
        load_qualified_study_fixture(
            ObjectStore(tmp_path / "store"),
            {"pilot": digest_bytes(pilot.read_bytes())},
            image=image,
        )
    with pytest.raises(ValueError, match="fixture identity differs"):
        load_qualified_study_fixture(
            ObjectStore(tmp_path / "store"),
            {"pilot": "sha256:" + "0" * 64},
            image=image,
        )


def test_prepare_refuses_image_identity_drift(tmp_path: Path) -> None:
    manifest = PILOT.parent / "dispatch-handler" / "qualification" / "manifest.json"
    image = json.loads(manifest.read_bytes())["observed_runtime_image_digest"]
    different_image = "sha256:" + ("0" if image[-1] != "0" else "1") * 64
    with pytest.raises(ValueError, match="image identity differs from qualification"):
        load_qualified_study_fixture(
            ObjectStore(tmp_path / "store"),
            {"dispatch-handler": digest_bytes(manifest.read_bytes())},
            image=different_image,
        )


def test_prepare_refuses_unusable_pricing_basis(tmp_path: Path) -> None:
    values = configuration()
    values["pricing"] = {"basis": "provider-catalogue", "conservative_request_bound_usd": None}
    config = RunConfiguration.model_validate(values)
    with pytest.raises(LaunchRefused, match="pricing_basis_unusable"):
        _build(config, ObjectStore(tmp_path / "store"), live=False)


def test_prepare_refuses_missing_routing_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CODE_EXTENSION_ROUTING_CONFIG", raising=False)
    config = RunConfiguration.model_validate(configuration())
    with pytest.raises(LaunchRefused, match="routing_artifact_unavailable"):
        _build(config, ObjectStore(tmp_path / "store"), live=False)
    monkeypatch.setenv("CODE_EXTENSION_ROUTING_CONFIG", str(tmp_path / "missing.yaml"))
    with pytest.raises(LaunchRefused, match="routing_artifact_unavailable"):
        _build(config, ObjectStore(tmp_path / "store"), live=False)


def test_prepare_refuses_routing_identity_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    routing = tmp_path / "routing.yaml"
    routing.write_text("changed route")
    monkeypatch.setenv("CODE_EXTENSION_ROUTING_CONFIG", str(routing))
    monkeypatch.setattr(
        "code_extension.run.load_qualified_study_fixture",
        lambda *_args, **_kwargs: SimpleNamespace(
            manifest=SimpleNamespace(routing_config_digest="sha256:" + "0" * 64)
        ),
    )
    config = RunConfiguration.model_validate(configuration())
    with pytest.raises(LaunchRefused, match="routing_identity_drift"):
        _build(config, ObjectStore(tmp_path / "store"), live=False)


@pytest.mark.asyncio
async def test_worker_refuses_coordinate_outside_declared_plan(tmp_path: Path) -> None:
    worker = ExtensionStudyWorker(
        arm_id="baseline", bridges={}, adapters={}, config_digest="sha256:" + "a" * 64
    )
    coordinate = CellCoordinate(
        subject_id="foreign-scenario",
        arm_id="baseline",
        worker_repeat=0,
        realization_ref="sha256:" + "b" * 64,
    )
    with pytest.raises(LaunchRefused, match="coordinate is not one of the plan's declared cells"):
        await worker.run_cell(input_value={}, coordinate=coordinate)
    worker.adapters = {"foreign-scenario": cast(Any, None)}
    worker.allowed_coordinates = {coordinate.id: coordinate.realization_ref}
    wrong_repeat = coordinate.model_copy(update={"worker_repeat": 1})
    wrong_realization = coordinate.model_copy(update={"realization_ref": "sha256:" + "c" * 64})
    for foreign_coordinate in (wrong_repeat, wrong_realization):
        with pytest.raises(
            LaunchRefused, match="coordinate is not one of the plan's declared cells"
        ):
            await worker.run_cell(input_value={}, coordinate=foreign_coordinate)
    assert not (tmp_path / "attempts.jsonl").exists()


@pytest.mark.asyncio
async def test_route_probe_charges_spend_and_refuses_model_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = RunConfiguration.model_validate(configuration())
    plan_digest = "sha256:" + "d" * 64
    observed_gates: list[SpendGate] = []

    async def joined_thread(function: Callable[..., Any], *args: object) -> Any:
        # This sandbox cannot wake asyncio.to_thread futures, so join the same work here.
        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(function, *args).result()

    monkeypatch.setattr("code_extension.run.asyncio.to_thread", joined_thread)

    async def probe(worker_model: str, root: Path) -> tuple[SpendGate, AttemptJournal]:
        gate = SpendGate(config.total_cap_usd)
        observed_gates.append(gate)
        journal = AttemptJournal(root / "attempts.jsonl", plan_digest, config.digest())

        class Client:
            async def complete_payload(self, _payload: object) -> SimpleNamespace:
                return SimpleNamespace(worker_model=worker_model, cost_usd=0.005)

            async def aclose(self) -> None:
                pass

        class Factory:
            def create(self, *, idempotency_key: str) -> Client:
                assert idempotency_key == plan_digest + ":route-probe"
                return Client()

        worker = SimpleNamespace(
            gate=gate,
            journal=journal,
            request_bound=Decimal("0.01"),
            bridges={"scenario": SimpleNamespace(factory=Factory())},
        )
        prepared = cast(PreparedStudy, SimpleNamespace(workers={"baseline": worker}))
        await _route_probe(config, ObjectStore(root / "store"), plan_digest, prepared)
        return gate, journal

    gate, journal = await probe(config.route.model, tmp_path / "passing")
    assert gate.requests == 1
    assert gate.spent_usd == Decimal("0.005")
    assert [record["event"] for record in journal.records()] == [
        "attempt_started", "reserved", "finished"
    ]
    assert journal.records()[-1]["status"] == "settled"

    with pytest.raises(LaunchRefused, match="route_probe_model_mismatch"):
        await probe("another-model", tmp_path / "mismatch")
    mismatch = AttemptJournal(
        tmp_path / "mismatch" / "attempts.jsonl", plan_digest, config.digest()
    )
    assert mismatch.records()[-1]["status"] == "billing_uncertain"
    assert mismatch.records()[-1]["cost_usd"] is None
    assert observed_gates[-1].spent_usd == Decimal("0.01")
    assert observed_gates[-1].halt == "billing_uncertain"


@pytest.mark.asyncio
async def test_execute_refuses_wrong_digest_before_dispatch(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"fake": "plan"}))
    with pytest.raises(LaunchRefused, match="supplied .* actual"):
        await execute(plan, "sha256:" + "a" * 64, tmp_path)
