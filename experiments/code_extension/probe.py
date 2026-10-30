"""Model-free production-agent probes for a sidecar-backed scenario."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from workflow_edit.bridge import ModelTurn, RepositoryAgentClient  # type: ignore[attr-defined]
from workflow_edit.bridge import bridge as bridge_protocol  # type: ignore[attr-defined]

from assay.canonical import canonical_json, digest_bytes
from assay.fixture_manifest import FixtureManifestV3
from assay.pier_protocol import CandidateSubmission
from assay.store import ObjectStore
from code_extension.bridge import EXTENSION_TOOLS  # type: ignore[attr-defined]
from code_extension.evaluation import evaluate_scenario_candidate
from code_extension.fixture import materialize, read_tree
from code_extension.fixtures import ScenarioFixture
from code_extension.qualify import make_runner, observed_image_digest

IMAGE = "assay-code-extension:run-bfb5dd7d9189a983"
SUBMIT = {
    "summary": "Scripted qualification",
    "self_assessed_verdict": "complete",
    "checks_performed": "model-free",
    "remaining_work": None,
}


def _scripted_client(
    fixture: ScenarioFixture,
    image: str,
    root: Path,
    commands: list[tuple[str, dict[str, Any]]],
) -> RepositoryAgentClient:
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

    return RepositoryAgentClient(
        api_key=None,
        image=image,
        runs_root=root,
        model_route=bridge_protocol.ModelRoute(
            endpoint="http://willie:8900", model="qwen-coder-32b", provider="smithers-local"
        ),
        completion=complete,
        tools=EXTENSION_TOOLS,
        extension_mode=True,
        writable_prefixes=tuple(
            prefix
            for prefix in fixture.sidecar.writable_implementation_scope
            if prefix.endswith("/")
        ),
    )


def _package(fixture: ScenarioFixture) -> dict[str, str]:
    return {
        "instruction.md": fixture.task,
        **{f"workspace/{name}": source for name, source in fixture.repository.items()},
    }


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
            image,
            root,
            [
                ("write_file", {"path": "src/domain/run-event.ts", "content": source}),
            ],
        )
        result = client.run_cell(cell_id="dispatch-handler:baseline:w0", package=_package(fixture))
        store = ObjectStore(root / "objects")
        for group in fixture.groups:
            store.publish_bytes(canonical_json(group.model_dump(mode="json")))
        patch_ref = store.publish_bytes(result.patch).digest
        candidate = CandidateSubmission(
            patch_ref=patch_ref,
            tree_digest=result.final_tree_digest,
            baseline_tree_digest=result.baseline_tree_digest,
        )
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
        return {
            "schema_version": "assay-extension-scripted-submission/0.1.0",
            "image_digest": manifest.observed_runtime_image_digest,
            "tool_path": ["write_file", "submit_output"],
            "patch_digest": digest_bytes(result.patch),
            "reference_tree_matches": read_tree(patched)
            == {name: data.decode() for name, data in result.files.items()},
            "independent_evaluator_verdict": verdict.verdict,
            "groups": {group.name: group.status for group in verdict.groups},
            "tool_outputs": [
                str(message.get("content", ""))
                for message in result.trajectory["messages"]
                if message.get("role") == "tool"
            ],
        }


def access_probe(fixture: ScenarioFixture, image: str) -> dict[str, object]:
    """Attempt forbidden reads through every tool, including shell and symlink paths."""

    def shell_read(path: str) -> tuple[str, dict[str, Any]]:
        command = f"if cat {path} >/dev/null 2>&1; then echo REACHED; else echo REFUSED; fi"
        return ("run_command", {"command": command})

    attempts: list[tuple[str, dict[str, Any]]] = [
        ("read_file", {"path": "tests/hidden/new-behavior/work-started.test.ts"}),
        ("read_file", {"path": "../patches/reference.patch"}),
        ("read_file", {"path": "../patches/missing-registration.patch"}),
        ("read_file", {"path": "../patches/missing-validation.patch"}),
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
        shell_read("/cache/operator/manifest.json"),
        shell_read("/home/steve/.ssh/id_rsa"),
        ("run_command", {"command": "ln -s /home/steve/.ssh/id_rsa src/domain/probe-link"}),
        ("read_file", {"path": "src/domain/probe-link"}),
        ("run_command", {"command": "rm src/domain/probe-link"}),
    ]
    with tempfile.TemporaryDirectory() as scratch:
        client = _scripted_client(fixture, image, Path(scratch), attempts)
        result = client.run_cell(cell_id="dispatch-handler:probe:w0", package=_package(fixture))
    replies = [
        message for message in result.trajectory["messages"] if message.get("role") == "tool"
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
            "exit=0\nREFUSED" if 8 <= index <= 13 else ("exit=0" if index in {14, 16} else "error:")
        )
        if not response.startswith(expected):
            raise ValueError(f"access probe attempt {index} reached an unexpected result")
    if result.final_tree_digest != fixture.tree_digest:
        raise ValueError("access probe changed the submitted repository")
    return {
        "schema_version": "assay-extension-access-probe/0.1.0",
        "image_digest": observed_image_digest(image),
        "attempts": observations,
        "tools_exercised": sorted({name for name, _ in attempts} | {"submit_output"}),
        "submitted": result.summary == SUBMIT["summary"],
        "candidate_unchanged": result.final_tree_digest == fixture.tree_digest,
    }
