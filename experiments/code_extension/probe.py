"""Model-free production-agent probes for a sidecar-backed scenario."""

from __future__ import annotations

import json
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from assay_pier_bridge.identity import package_digest
from workflow_edit.bridge import ModelTurn

from assay.adapters.pier import BridgeTrialResult
from assay.adapters.smithers import SmithersFactory
from assay.canonical import canonical_json, digest_bytes
from assay.fixture_manifest import FixtureManifestV3
from assay.models import CellCoordinate
from assay.pier_protocol import CandidateSubmission, RuntimeBinding, bind_exchange
from assay.store import ObjectStore
from code_extension.bridge import EXTENSION_SYSTEM_PROMPT, ExtensionBridgeClient
from code_extension.evaluation import evaluate_scenario_candidate
from code_extension.fixture import materialize, read_tree
from code_extension.fixtures import ScenarioFixture
from code_extension.qualify import make_runner, observed_image_digest

IMAGE = "assay-code-extension:ce-v1-bounds"
SUBMIT = {
    "summary": "Scripted qualification",
    "self_assessed_verdict": "complete",
    "checks_performed": "model-free",
    "remaining_work": None,
}


class _NoModelFactory:
    """Supply route metadata while scripted turns prevent model dispatch."""

    model = "qwen-coder-32b"

    def configuration(self) -> dict[str, str]:
        return {"model": self.model, "backend": "scripted-qualification"}

    def create(self, **_kwargs: object) -> None:
        raise AssertionError("model dispatch is forbidden in qualification")


def _scripted_client(
    fixture: ScenarioFixture,
    manifest: FixtureManifestV3,
    image: str,
    root: Path,
    commands: list[tuple[str, dict[str, Any]]],
) -> ExtensionBridgeClient:
    turns = [*commands, ("submit_output", SUBMIT)]

    def complete(
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
        turn: int,
        deadline: float | None,
    ) -> ModelTurn:
        name, arguments = turns[turn - 1]
        return ModelTurn(
            message={
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"script-{turn}",
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(arguments)},
                    }
                ],
            },
            finish_reason="tool_calls",
            prompt_tokens=0,
            completion_tokens=0,
            cost_usd=None,
        )

    scenario = manifest.scenario(fixture.subject_id)
    if scenario is None:
        raise ValueError("scripted scenario is absent from its manifest")
    return ExtensionBridgeClient(
        image=image,
        runs_root=root,
        factory=cast(SmithersFactory, _NoModelFactory()),
        run_label="dispatch-handler-model-free",
        completion_for=lambda _cell_key: complete,
        scenario=scenario,
        arm_set=manifest.arm_set,
        arm_id="baseline",
    )


def _package(fixture: ScenarioFixture) -> dict[str, str]:
    return {
        "instruction.md": fixture.task,
        **{f"workspace/{name}": source for name, source in fixture.repository.items()},
    }


def _run_script(
    client: ExtensionBridgeClient,
    fixture: ScenarioFixture,
    image: str,
) -> tuple[BridgeTrialResult, dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Enter through the same bridge trial and configuration checks as a live cell."""
    package = _package(fixture)
    configuration = client.configuration()
    coordinate = CellCoordinate(
        subject_id=fixture.subject_id,
        arm_id="baseline",
        worker_repeat=0,
        realization_ref=digest_bytes(fixture.tree_digest.encode()),
    )
    exchange = bind_exchange(
        coordinate=coordinate,
        binding=RuntimeBinding(
            runtime_version="extension-scripted-qualification/1",
            image_digest=observed_image_digest(image),
            configuration_ref=digest_bytes(canonical_json(configuration)),
            package_digest=package_digest(package),
        ),
    )
    result = client.create(exchange=exchange, package=package).run()
    if not isinstance(result.outcome, CandidateSubmission):
        raise ValueError(f"scripted bridge returned {result.outcome}")
    trajectory = json.loads(result.artifacts["trajectory.json"])
    observed_configuration = json.loads(result.artifacts["configuration.json"])
    report = json.loads(result.artifacts["result.json"])
    if (
        observed_configuration != configuration
        or configuration["writable_prefixes"] != list(fixture.sidecar.writable_implementation_scope)
        or configuration["system_prompt_sha256"]
        != digest_bytes(EXTENSION_SYSTEM_PROMPT.encode())
        or trajectory["messages"][0] != {"role": "system", "content": EXTENSION_SYSTEM_PROMPT}
        or configuration["bounds"] != asdict(client._bounds())
    ):
        raise ValueError("scripted bridge configuration differs from the live extension arm")
    return result, trajectory, configuration, report


async def reference_submission(
    fixture: ScenarioFixture,
    manifest: FixtureManifestV3,
    image: str,
) -> dict[str, object]:
    """Apply the known patch via write_file and submit_output, then independently grade it."""
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        patched = root / "patched"
        patched.mkdir()
        materialize(patched, fixture.repository, fixture.arms[0].reference_patch)
        source = (patched / "src/domain/run-event.ts").read_text()
        client = _scripted_client(
            fixture,
            manifest,
            image,
            root,
            [
                ("write_file", {"path": "src/domain/run-event.ts", "content": source}),
            ],
        )
        result, trajectory, configuration, _ = _run_script(client, fixture, image)
        store = ObjectStore(root / "objects")
        for group in fixture.groups:
            store.publish_bytes(canonical_json(group.model_dump(mode="json")))
        patch = result.artifacts["candidate.patch"]
        patch_ref = store.publish_bytes(patch).digest
        candidate = cast(CandidateSubmission, result.outcome)
        if candidate.patch_ref != patch_ref:
            raise ValueError("scripted bridge patch differs from its bound candidate")
        verdict = await evaluate_scenario_candidate(
            store=store,
            manifest=manifest,
            subject_id=fixture.subject_id,
            arm_id="baseline",
            baseline=fixture.repository,
            submission=candidate,
            runner=make_runner(manifest.observed_runtime_image_digest),
        )
        if verdict.verdict != "correct":
            raise ValueError(
                f"scripted reference submission was {verdict.verdict}: {verdict.cause}"
            )
        captured = root / "captured"
        captured.mkdir()
        materialize(captured, fixture.repository, patch.decode())
        return {
            "schema_version": "assay-extension-scripted-submission/0.1.0",
            "image_digest": manifest.observed_runtime_image_digest,
            "tool_path": ["write_file", "submit_output"],
            "patch_digest": digest_bytes(patch),
            "reference_tree_matches": read_tree(patched) == read_tree(captured),
            "independent_evaluator_verdict": verdict.verdict,
            "groups": {group.name: group.status for group in verdict.groups},
            "writable_prefixes": configuration["writable_prefixes"],
            "system_prompt_sha256": configuration["system_prompt_sha256"],
            "bounds": configuration["bounds"],
            "tool_outputs": [
                str(message.get("content", ""))
                for message in trajectory["messages"]
                if message.get("role") == "tool"
            ],
        }


def access_probe(
    fixture: ScenarioFixture, manifest: FixtureManifestV3, image: str
) -> dict[str, object]:
    """Attempt forbidden reads through every tool, including shell and symlink paths."""

    def shell_read(path: str) -> tuple[str, dict[str, Any]]:
        command = f"if cat {path} >/dev/null 2>&1; then echo REACHED; else echo REFUSED; fi"
        return ("run_command", {"command": command})

    attempts: list[tuple[str, dict[str, Any]]] = [
        ("read_file", {"path": "tests/hidden/new-behavior/work-started.test.ts"}),
        ("read_file", {"path": "../patches/reference.patch"}),
        ("read_file", {"path": "../patches/missing-registration.patch"}),
        ("read_file", {"path": "../patches/missing-validation.patch"}),
        ("read_file", {"path": "../patches/missing-type-export.patch"}),
        ("read_file", {"path": "/cache/operator/manifest.json"}),
        ("read_file", {"path": "/home/steve/.ssh/id_rsa"}),
        ("write_file", {"path": "../patches/probe.txt", "content": "probe"}),
        (
            "replace_in_file",
            {"path": "tests/hidden/regression/probe.test.ts", "old": "probe", "new": "changed"},
        ),
        shell_read("tests/hidden/new-behavior/work-started.test.ts"),
        shell_read("patches/reference.patch"),
        shell_read("patches/missing-registration.patch"),
        shell_read("patches/missing-validation.patch"),
        shell_read("patches/missing-type-export.patch"),
        shell_read("/cache/operator/manifest.json"),
        shell_read("/home/steve/.ssh/id_rsa"),
        ("run_command", {"command": "ln -s /home/steve/.ssh/id_rsa src/domain/probe-link"}),
        ("read_file", {"path": "src/domain/probe-link"}),
        ("run_command", {"command": "rm src/domain/probe-link"}),
    ]
    with tempfile.TemporaryDirectory() as scratch:
        client = _scripted_client(fixture, manifest, image, Path(scratch), attempts)
        result, trajectory, configuration, report = _run_script(client, fixture, image)
    replies = [
        message for message in trajectory["messages"] if message.get("role") == "tool"
    ]
    observations = [
        {
            "tool": name,
            "target": args.get("path", args.get("command", "")),
            "response": str(replies[index].get("content", ""))[:200]
            if index < len(replies)
            else "missing",
        }
        for index, (name, args) in enumerate(attempts)
    ]
    for index, observation in enumerate(observations):
        response = str(observation["response"])
        expected = (
            "exit=0\nREFUSED" if 9 <= index <= 15 else ("exit=0" if index in {16, 18} else "error:")
        )
        if not response.startswith(expected):
            raise ValueError(f"access probe attempt {index} reached an unexpected result")
    candidate = cast(CandidateSubmission, result.outcome)
    if candidate.tree_digest != fixture.tree_digest:
        raise ValueError("access probe changed the submitted repository")
    return {
        "schema_version": "assay-extension-access-probe/0.1.0",
        "image_digest": observed_image_digest(image),
        "attempts": observations,
        "tools_exercised": sorted({name for name, _ in attempts} | {"submit_output"}),
        "submitted": report["summary"] == SUBMIT["summary"],
        "candidate_unchanged": candidate.tree_digest == fixture.tree_digest,
        "writable_prefixes": configuration["writable_prefixes"],
        "system_prompt_sha256": configuration["system_prompt_sha256"],
        "bounds": configuration["bounds"],
    }
