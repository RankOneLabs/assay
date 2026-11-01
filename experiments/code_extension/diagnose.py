"""Replay recorded extension failures in the pinned image without changing verdicts."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from workflow_edit.evaluation import WorkerCandidate, worker_candidate

from assay.canonical import canonical_json
from assay.fixture_manifest import FixtureManifestV3
from assay.investigations.workflow_correctness import (
    DockerWorkflowRunner,
    WorkflowRunnerSettings,
    workflow_tree_digest,
)
from assay.models import ExecutionOutcome, ExecutionPlanV3, RunManifest
from assay.pier_protocol import CandidateSubmission
from assay.store import ObjectStore
from code_extension.evaluation import GRADER_REVISION, evaluate_scenario_candidate
from code_extension.fixture import PILOT, PilotFixture, load_fixture, materialize, read_tree
from code_extension.metrics import artifact_bytes
from code_extension.qualify import require_image

_FAIL = re.compile(r"^\(fail\) (.*?)(?: \[[\d.]+ms\])?$", re.MULTILINE)
_TS_ERROR = re.compile(r"^(\S+\.ts)\(\d+,\d+\): error (TS\d+): (.*)$", re.MULTILINE)
TYPECHECK = ("tsc", "--noEmit", "-p", "tsconfig.json")
_REPLAY = """import json
import subprocess
import sys
from pathlib import Path

payload = json.loads(sys.stdin.buffer.read())
root = Path('/tmp/extension-diagnose')
root.mkdir()
for name, source in payload['tree'].items():
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding='utf-8')
result = subprocess.run(payload['command'], cwd=root, capture_output=True,
                        timeout=180, check=False)
sys.stdout.buffer.write(result.stdout + result.stderr)
"""


def _reset_visible_tests(root: Path, fixture: PilotFixture) -> None:
    visible = root / "tests" / "visible"
    if visible.exists():
        shutil.rmtree(visible)
    for group in fixture.groups:
        if group.restores:
            for name, source in group.files.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source, encoding="utf-8")


def _install_hidden_tests(root: Path, fixture: PilotFixture) -> None:
    for group in fixture.groups:
        if not group.restores:
            for name, source in group.files.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source, encoding="utf-8")


def _run(image: str, root: Path, argv: Sequence[str]) -> str:
    name = "assay-extension-diagnose-" + uuid.uuid4().hex
    try:
        completed = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--name",
                name,
                "--pull=never",
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--pids-limit",
                "64",
                "--memory",
                "512m",
                "--cpus",
                "1",
                "--tmpfs",
                "/tmp:rw,nosuid,nodev,size=256m",
                "--user",
                "65534:65534",
                "--env",
                "HOME=/tmp",
                "--env",
                "BUN_INSTALL_CACHE_DIR=/tmp/bun",
                "--workdir",
                "/tmp",
                "--entrypoint",
                "python",
                "-i",
                image,
                "-I",
                "-S",
                "-c",
                _REPLAY,
            ],
            input=canonical_json({"tree": read_tree(root), "command": list(argv)}),
            capture_output=True,
            timeout=300,
            check=False,
        )
        if completed.returncode:
            raise RuntimeError("diagnosis sandbox failed")
        return (completed.stdout + completed.stderr).decode("utf-8", errors="replace")
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)


def diagnose_candidate(
    image: str,
    fixture: PilotFixture,
    patch: str,
    groups: Mapping[str, Mapping[str, str | None]],
    *,
    scratch: Path,
    manifest: FixtureManifestV3 | None = None,
) -> dict[str, object]:
    """Return names for already-failed groups; the caller's record is never edited."""
    if manifest is not None:
        require_image(manifest, image)
    commands = {group.name: group.command for group in fixture.groups}
    if set(groups) - commands.keys():
        raise ValueError("unknown recorded group")
    causes = {group.get("cause") for group in groups.values() if group.get("cause")}
    preflight = sorted(
        cause
        for cause in causes
        if cause is not None
        and (
            cause.startswith(("typecheck_", "build_"))
            or cause
            in {
                "patch_rejected",
                "test_path_collision",
                "toolchain_unavailable",
                "candidate_tree_digest_mismatch",
                "sandbox_protocol_error",
            }
        )
    )
    cause = preflight[0] if preflight else None
    if cause is not None and cause != "typecheck_nonzero_exit":
        return {"preflight_cause": cause}
    root = Path(tempfile.mkdtemp(dir=scratch))
    root.chmod(0o755)
    try:
        materialize(root, fixture.repository, patch)
        _reset_visible_tests(root, fixture)
        if cause == "typecheck_nonzero_exit":
            errors = _TS_ERROR.findall(_run(image, root, TYPECHECK))
            return {
                "preflight_cause": cause,
                "typecheck_errors": [
                    {"file": file, "code": code, "message": message}
                    for file, code, message in errors[:5]
                ],
            }
        _install_hidden_tests(root, fixture)
        return {
            "failing_tests": {
                name: sorted(
                    set(
                        _FAIL.findall(
                            _run(
                                image,
                                root,
                                next(
                                    group.command for group in fixture.groups if group.name == name
                                ),
                            )
                        )
                    )
                )
                for name, group in sorted(groups.items())
                if group.get("status") == "failed"
            }
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def regrade_archive(archive: Path, image: str, output: Path) -> tuple[Path, ...]:
    """Replay retained candidates with the independent evaluator, appending new records."""
    runs = archive / "runs" if (archive / "runs").is_dir() else archive
    destination = output / "regrades"
    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for index_path in sorted(runs.glob("*/run.json")):
        index = json.loads(index_path.read_text(encoding="utf-8"))
        store = ObjectStore(index_path.parent)
        plan = ExecutionPlanV3.model_validate_json(store.read_bytes(index["plan_ref"]))
        manifest = RunManifest.model_validate_json(store.read_bytes(index["manifest_ref"]))
        fixture_root = archive / "fixtures" if (archive / "fixtures").is_dir() else PILOT.parent
        fixtures = [
            FixtureManifestV3.model_validate_json(path.read_bytes())
            for path in sorted(fixture_root.glob("*/qualification/manifest.json"))
        ]
        by_subject = {
            scenario.subject_id: fixture for fixture in fixtures for scenario in fixture.scenarios
        }
        runner = DockerWorkflowRunner(WorkflowRunnerSettings(image=image, toolchain="bun"))
        for cell in plan.cells:
            execution_ref = manifest.execution_records.get(cell.id)
            if execution_ref is None:
                continue
            outcome = ExecutionOutcome.model_validate_json(store.read_bytes(execution_ref))
            realization = json.loads(store.read_bytes(cell.realization_ref))
            baseline = realization["repository"]
            if not isinstance(baseline, dict):
                raise ValueError("archived realization has no repository")
            if outcome.output_ref is not None:
                payload = json.loads(store.read_bytes(outcome.output_ref))
                candidate = worker_candidate(store, payload)
            else:
                trace_ref = outcome.trace_ref or manifest.interruption_ref
                trace = json.loads(store.read_bytes(trace_ref)) if trace_ref else {}
                refs = trace.get("artifact_refs", {})
                patch_ref = refs.get("stopped/candidate.patch") or refs.get("candidate.patch")
                if not isinstance(patch_ref, str):
                    continue
                patch = artifact_bytes(store, patch_ref)
                baseline_digest = workflow_tree_digest(baseline)
                with tempfile.TemporaryDirectory() as candidate_scratch:
                    root = Path(candidate_scratch)
                    try:
                        materialize(root, baseline, patch.decode("utf-8"))
                        candidate_digest = workflow_tree_digest(read_tree(root))
                    except (subprocess.CalledProcessError, UnicodeError, ValueError):
                        candidate_digest = baseline_digest
                candidate = WorkerCandidate(patch, candidate_digest, baseline_digest)
            fixture = by_subject[cell.subject_id]
            replay_fixture = fixture.model_copy(update={"observed_runtime_image_digest": image})
            with tempfile.TemporaryDirectory() as scratch:
                replay_store = ObjectStore(Path(scratch))
                scenario = fixture.scenario(cell.subject_id)
                assert scenario is not None
                for group in (*scenario.visible_tests, *scenario.hidden_tests):
                    replay_store.publish_bytes(store.read_bytes(group.digest))
                submission = CandidateSubmission(
                    patch_ref=str(replay_store.publish_bytes(candidate.patch)),
                    tree_digest=candidate.tree_digest,
                    baseline_tree_digest=candidate.baseline_tree_digest,
                )
                result = asyncio.run(
                    evaluate_scenario_candidate(
                        store=replay_store,
                        manifest=replay_fixture,
                        subject_id=cell.subject_id,
                        arm_id=cell.arm_id,
                        baseline=baseline,
                        submission=submission,
                        runner=runner,
                    )
                )
            record = {
                "schema_version": "code-extension-regrade/1",
                "image_digest": image,
                "grader_revision": GRADER_REVISION,
                "run_id": manifest.run_id,
                "cell_id": cell.id,
                "original_manifest_ref": index["manifest_ref"],
                "original_grading_refs": {
                    key: ref
                    for key, ref in manifest.evaluation_records.items()
                    if key.startswith(f"{cell.id}:")
                },
                "verdict": result.verdict,
                "cause": result.cause,
                "groups": [asdict(group) for group in result.groups],
                "preflight": asdict(result.preflight) if result.preflight is not None else None,
                "attribution": result.attribution,
                "rejected_changes": [asdict(change) for change in result.rejected_changes],
            }
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            path = destination / f"{stamp}-{uuid.uuid4().hex}.json"
            with path.open("x", encoding="utf-8") as stream:
                stream.write(canonical_json(record).decode("utf-8") + "\n")
            written.append(path)
    return tuple(written)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="assay-code-extension:ce-v1-cme")
    parser.add_argument("--manifest", type=Path, default=PILOT / "qualification" / "manifest.json")
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--patch", type=Path, required=True)
    args = parser.parse_args()
    manifest = FixtureManifestV3.model_validate_json(args.manifest.read_bytes())
    record = json.loads(args.record.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as scratch:
        diagnosis = diagnose_candidate(
            args.image,
            load_fixture(),
            args.patch.read_text(encoding="utf-8"),
            record["groups"],
            scratch=Path(scratch),
            manifest=manifest,
        )
    print(json.dumps(diagnosis, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
