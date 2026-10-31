"""Operator configuration and command surface checks."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from code_extension.config import RunConfiguration
from code_extension.fixture import PILOT
from code_extension.protocol import ORDERED_TOOL_SCHEMAS_SHA256, SYSTEM_PROMPT_SHA256
from code_extension.run import LaunchRefused, execute, main, prepare
from code_extension.settings import ExtensionAgentSettings
from code_extension.study import load_qualified_study_fixture

from assay.canonical import digest_bytes
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
    seen: list[str] = []
    monkeypatch.setattr("code_extension.run.qualify.main", lambda: seen.extend(sys.argv))
    monkeypatch.setattr(
        sys, "argv", ["run", "qualify", "--scenario", "pilot", "--image", "sha256:" + "a" * 64]
    )
    main()
    assert seen[0] == "code_extension.qualify"
    assert seen[1:] == ["--scenario", "pilot", "--image", "sha256:" + "a" * 64]


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
    monkeypatch.setattr(
        "assay.adapters.smithers.SmithersFactory.create",
        lambda *args, **kw: pytest.fail("prepare reached a model client"),
    )
    first = prepare(config_path, tmp_path / "store")
    second = prepare(config_path, tmp_path / "store")
    assert first["digest"] == second["digest"]
    assert Path(first["plan"]).read_bytes() == Path(second["plan"]).read_bytes()
    assert first["attempts"] == 1
    noncanonical = tmp_path / "noncanonical.json"
    noncanonical.write_text(json.dumps(json.loads(Path(first["plan"]).read_bytes()), indent=2))
    with pytest.raises(ValueError, match="canonical wire JSON"):
        asyncio.run(execute(noncanonical, digest_bytes(noncanonical.read_bytes()), tmp_path / "store"))


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


@pytest.mark.asyncio
async def test_execute_refuses_wrong_digest_before_dispatch(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"fake": "plan"}))
    with pytest.raises(LaunchRefused, match="supplied .* actual"):
        await execute(plan, "sha256:" + "a" * 64, tmp_path)
