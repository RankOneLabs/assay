"""Offline, per-arm qualification and manifest assembly for extension fixtures.

The retained records contain group verdicts and causes, never test output.
Reference patches are used only to prove that the frozen checks can pass.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from assay.canonical import canonical_json, digest_bytes
from assay.fixture_manifest import (
    BaselineArmSet,
    ExtensionArmQualification,
    ExtensionArmRealization,
    ExtensionScenario,
    FixtureManifestV3,
    NamedTestGroup,
    QualificationResult,
)
from assay.investigations.workflow_correctness import (
    DockerWorkflowRunner,
    WorkflowCorrectnessResult,
    WorkflowRunnerSettings,
    WorkflowTestGroup,
    workflow_tree_digest,
)
from code_extension.fixture import (
    CHECKPOINT_SHA,
    PILOT,
    SUBJECT_ID,
    PilotFixture,
    load_fixture,
    materialize,
    read_tree,
)

IMAGE_TAG = "assay-code-extension:ce-v1-bounds"
CHECKS = ("baseline_passes", "feature_fails", "reference_passes")
EXPECTED = {"baseline_passes": "passed", "feature_fails": "failed", "reference_passes": "passed"}
ExpectedOutcome = Literal["passed", "failed"]


def observed_image_digest(image: str) -> str:
    result = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    digest = result.stdout.strip()
    if not digest.startswith("sha256:") or len(digest) != 71:
        raise ValueError("Docker did not return a sha256 image digest")
    return digest


def require_image(manifest: FixtureManifestV3, image: str) -> str:
    observed = observed_image_digest(image)
    if manifest.observed_runtime_image_digest != observed:
        raise ValueError("manifest image digest differs from the runner's current image")
    return observed


def make_runner(image_digest: str) -> DockerWorkflowRunner:
    result = subprocess.run(
        ["docker", "version", "--format", "{{.Client.Version}} {{.Server.Version}}"],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    versions = result.stdout.split()
    if len(versions) != 2:
        raise ValueError("Docker did not return client and server versions")
    return DockerWorkflowRunner(
        WorkflowRunnerSettings(
            image=image_digest,
            toolchain="bun",
            docker_client_version=versions[0],
            docker_server_version=versions[1],
            candidate_timeout_s=60,
            deadline_s=300,
        )
    )


def _record(
    fixture: PilotFixture,
    arm_id: str,
    check: str,
    image_digest: str,
    patch_digest: str,
    result: WorkflowCorrectnessResult,
) -> dict[str, object]:
    statuses = {group.name: group.status for group in result.groups}
    if check == "baseline_passes":
        outcome = (
            "unavailable"
            if any(status == "unavailable" for status in statuses.values())
            else "passed"
            if all(
                statuses.get(name) == "passed"
                for name in ("visible_regression", "hidden_regression")
            )
            else "failed"
        )
    elif check == "feature_fails":
        # A preflight failure is not evidence that the feature checks are live.
        outcome = (
            "failed"
            if (
                statuses.get("visible_regression") == "passed"
                and statuses.get("hidden_regression") == "passed"
                and statuses.get("new_behavior") == "failed"
                and result.cause == "group_failure"
            )
            else "passed"
            if statuses.get("new_behavior") == "passed"
            else "unavailable"
        )
    else:
        outcome = (
            "passed"
            if result.verdict == "correct"
            else ("unavailable" if result.verdict == "unavailable" else "failed")
        )
    return {
        "schema_version": "assay-extension-qualification-record/0.1.0",
        "subject_id": SUBJECT_ID,
        "arm_id": arm_id,
        "check": check,
        "image_digest": image_digest,
        "tree_digest": fixture.tree_digest,
        "patch_digest": patch_digest,
        "outcome": outcome,
        "cause": result.cause,
        "groups": {
            group.name: {"status": group.status, "cause": group.cause} for group in result.groups
        },
    }


def write_record(directory: Path, arm_id: str, check: str, record: Mapping[str, object]) -> str:
    if check not in CHECKS:
        raise ValueError(f"unknown qualification check: {check}")
    target = directory / arm_id / f"{check}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_json(dict(record)) + b"\n"
    target.write_bytes(data)
    return digest_bytes(data)


def read_evidence(directory: Path, arm_id: str, check: str) -> tuple[dict[str, object], str]:
    data = (directory / arm_id / f"{check}.json").read_bytes()
    value = json.loads(data)
    if not isinstance(value, dict) or canonical_json(value) + b"\n" != data:
        raise ValueError("qualification record is not canonical")
    return value, digest_bytes(data)


def _patched_digest(fixture: PilotFixture, patch: str) -> str:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        materialize(root, fixture.repository, patch)
        return workflow_tree_digest(read_tree(root))


async def run_checks(
    fixture: PilotFixture,
    runner: DockerWorkflowRunner,
    image_digest: str,
    evidence_dir: Path,
) -> None:
    if (
        runner.settings.image != image_digest
        or observed_image_digest(runner.settings.image) != image_digest
    ):
        raise ValueError("runner image differs from the observed image digest")
    for arm in fixture.arms:
        for check in CHECKS:
            patch = arm.reference_patch if check == "reference_passes" else ""
            expected_tree = _patched_digest(fixture, patch) if patch else fixture.tree_digest
            result = await runner.run(
                baseline=fixture.repository,
                baseline_tree_digest=fixture.tree_digest,
                expected_tree_digest=expected_tree,
                patch=patch,
                groups=fixture.groups,
            )
            write_record(
                evidence_dir,
                arm.arm_id,
                check,
                _record(
                    fixture,
                    arm.arm_id,
                    check,
                    image_digest,
                    digest_bytes(patch.encode()),
                    result,
                ),
            )


def _pin_path(name: str) -> str | None:
    if name.startswith("src/"):
        return "oakridge-dbos/" + name
    if name.startswith("tests/visible/"):
        return "oakridge-dbos/tests/" + name.removeprefix("tests/visible/")
    if name.startswith("workflow-config/"):
        return name
    return None


def _group(name: str, digest: str) -> NamedTestGroup:
    return NamedTestGroup(name=name, digest=digest)


def _group_status(groups: Mapping[str, object], name: str) -> object:
    group = groups.get(name)
    return group.get("status") if isinstance(group, dict) else None


def assemble_manifest(
    fixture: PilotFixture,
    evidence_dir: Path,
    *,
    image: str,
    routing_config: Path,
) -> FixtureManifestV3:
    image_digest = observed_image_digest(image)
    arms: list[ExtensionArmRealization] = []
    for arm in fixture.arms:
        qualifications: dict[str, QualificationResult] = {}
        for check in CHECKS:
            record, digest = read_evidence(evidence_dir, arm.arm_id, check)
            if (
                record.get("schema_version") != "assay-extension-qualification-record/0.1.0"
                or record.get("subject_id") != SUBJECT_ID
                or record.get("arm_id") != arm.arm_id
                or record.get("check") != check
                or record.get("image_digest") != image_digest
                or record.get("tree_digest") != fixture.tree_digest
                or record.get("patch_digest")
                != digest_bytes(
                    (arm.reference_patch if check == "reference_passes" else "").encode()
                )
            ):
                raise ValueError(f"stale qualification record: {arm.arm_id}/{check}")
            outcome = record.get("outcome")
            if outcome != EXPECTED[check]:
                raise ValueError(f"unqualified arm {arm.arm_id}: {check} was {outcome}")
            groups = record.get("groups")
            if not isinstance(groups, dict):
                raise ValueError(f"invalid qualification groups: {arm.arm_id}/{check}")

            if (
                _group_status(groups, "visible_regression") != "passed"
                or _group_status(groups, "hidden_regression") != "passed"
                or _group_status(groups, "new_behavior")
                != ("passed" if check == "reference_passes" else "failed")
                or (check == "feature_fails" and record.get("cause") != "group_failure")
            ):
                raise ValueError(f"invalid qualification verdicts: {arm.arm_id}/{check}")
            qualified_outcome: ExpectedOutcome = "failed" if check == "feature_fails" else "passed"
            qualifications[check] = QualificationResult(outcome=qualified_outcome, evidence=digest)
        arms.append(
            ExtensionArmRealization(
                arm_id=arm.arm_id,
                tree_digest=fixture.tree_digest,
                task_prompt=fixture.task,
                reference_patch=digest_bytes(arm.reference_patch.encode()),
                negative_patches=tuple(
                    digest_bytes(patch.encode()) for patch in arm.negative_patches
                ),
                qualification=ExtensionArmQualification(
                    baseline_passes=qualifications["baseline_passes"],
                    feature_fails=qualifications["feature_fails"],
                    reference_passes=qualifications["reference_passes"],
                ),
            )
        )
    visible, hidden_regression, new_behavior = fixture.groups

    def named_group(group: WorkflowTestGroup) -> NamedTestGroup:
        return _group(group.name, digest_bytes(canonical_json(group.model_dump(mode="json"))))

    included = tuple(
        sorted(path for name in fixture.repository if (path := _pin_path(name)) is not None)
    )
    manifest = FixtureManifestV3(
        schema_version="assay-fixture-manifest/0.3.0",
        arm_set=BaselineArmSet(factor="baseline", arm_ids=("baseline",)),
        observed_runtime_image_digest=image_digest,
        routing_config_digest=digest_bytes(routing_config.read_bytes()),
        scenarios=(
            ExtensionScenario(
                subject_id=SUBJECT_ID,
                checkpoint_sha=CHECKPOINT_SHA,
                included_paths=included,
                excluded_paths=(
                    "oakridge-dbos/src/storage",
                    "oakridge-dbos/src/http",
                    "oakridge-dbos/src/runtime",
                    "oakridge-dbos/src/workflows",
                    "oakridge-dbos/src/adapters",
                    "oakridge-dbos/tests/support",
                ),
                dependency_lock_digests={
                    "package-lock.json": digest_bytes(
                        fixture.repository["package-lock.json"].encode()
                    )
                },
                feature_request="Optional run-context bindings with a declared default",
                visible_requirements=(
                    "Accept string or null defaults on context slot bindings.",
                    "Use the default only when the pointer does not resolve.",
                    "A defaulted binding does not require its pointer at launch.",
                ),
                visible_tests=(named_group(visible),),
                hidden_tests=tuple(
                    named_group(group) for group in (hidden_regression, new_behavior)
                ),
                arms=tuple(arms),
            ),
        ),
    )
    manifest.require_qualified()
    return manifest


async def qualify(
    *,
    image: str,
    routing_config: Path,
    evidence_dir: Path,
    fixture: PilotFixture | None = None,
    expected_manifest: FixtureManifestV3 | None = None,
) -> FixtureManifestV3:
    loaded = fixture or load_fixture()
    image_digest = observed_image_digest(image)
    if (
        expected_manifest is not None
        and expected_manifest.observed_runtime_image_digest != image_digest
    ):
        raise ValueError("manifest image digest differs from the runner's current image")
    await run_checks(loaded, make_runner(image_digest), image_digest, evidence_dir)
    manifest = assemble_manifest(loaded, evidence_dir, image=image, routing_config=routing_config)
    if expected_manifest is not None and manifest != expected_manifest:
        raise ValueError("requalified manifest differs from the committed manifest")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default=IMAGE_TAG)
    parser.add_argument(
        "--routing-config",
        type=Path,
        default=Path.home() / "codes/rol/smithers/routing_config.yaml",
    )
    parser.add_argument("--evidence-dir", type=Path, default=PILOT / "qualification" / "evidence")
    parser.add_argument("--manifest", type=Path, default=PILOT / "qualification" / "manifest.json")
    parser.add_argument("--verify-committed", action="store_true")
    args = parser.parse_args()
    expected = (
        FixtureManifestV3.model_validate_json(args.manifest.read_bytes())
        if args.verify_committed
        else None
    )
    manifest = asyncio.run(
        qualify(
            image=args.image,
            routing_config=args.routing_config,
            evidence_dir=args.evidence_dir,
            expected_manifest=expected,
        )
    )
    if not args.verify_committed:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_bytes(canonical_json(manifest.model_dump(mode="json")) + b"\n")
    print(manifest.observed_runtime_image_digest)
    print("qualified", ", ".join(arm.arm_id for arm in manifest.scenarios[0].arms))


if __name__ == "__main__":
    main()
