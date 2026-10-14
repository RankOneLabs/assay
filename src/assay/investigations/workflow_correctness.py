"""Offline TypeScript correctness checks against one declared arm baseline."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import uuid
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import Field

from assay.canonical import canonical_json, digest_bytes
from assay.investigations.sandbox_lifecycle import SandboxLifecycle
from assay.models import Sha256Ref, WireModel
from assay.repository import validate_repository

GroupName = Literal["visible_regression", "hidden_regression", "new_behavior"]
Verdict = Literal["correct", "incorrect", "unavailable"]
GROUP_NAMES: tuple[GroupName, ...] = (
    "visible_regression",
    "hidden_regression",
    "new_behavior",
)


class WorkflowRunnerSettings(WireModel):
    image: Sha256Ref
    docker_client_version: str = "29.6.1"
    docker_server_version: str = "29.1.2"
    command_timeout_s: float = Field(default=5.0, gt=0)
    deadline_s: float = Field(default=120.0, gt=0)
    candidate_timeout_s: float = Field(default=10.0, gt=0)
    max_output_bytes: int = Field(default=131_072, gt=0)


class WorkflowTestGroup(WireModel):
    """Frozen tests copied in after the candidate patch has been applied."""

    name: GroupName
    files: dict[str, str]
    command: tuple[str, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class GroupResult:
    name: GroupName
    status: Literal["passed", "failed", "unavailable"]
    cause: str | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class WorkflowCorrectnessResult:
    verdict: Verdict
    groups: tuple[GroupResult, ...]
    cause: str | None = None


_HARNESS = r"""import json
import os
from pathlib import Path
import subprocess
import sys

payload = json.loads(sys.stdin.buffer.read())
root = Path('/tmp/workflow')
root.mkdir()
for name, source in payload['baseline'].items():
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding='utf-8')

def result(status, cause=None):
    return {'status': status, 'cause': cause}

def run(args, timeout):
    try:
        completed = subprocess.run(args, cwd=root, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return result('failed', 'candidate_timeout')
    except OSError:
        return result('unavailable', 'toolchain_unavailable')
    if len(completed.stdout) > payload['max_output_bytes']:
        return result('failed', 'output_limit')
    return result('passed') if completed.returncode == 0 else result('failed', 'nonzero_exit')

patch = subprocess.run(['git', 'apply', '-'], cwd=root,
                       input=payload['patch'].encode('utf-8'),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
if patch.returncode:
    outcome = {'preflight': result('failed', 'patch_rejected'), 'groups': {}}
else:
    for group in payload['groups']:
        for name, source in group['files'].items():
            target = root / name
            if not target.resolve().is_relative_to(root.resolve()):
                raise ValueError('test path escapes sandbox')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source, encoding='utf-8')
    try:
        tsc_version = subprocess.run(['tsc', '--version'], cwd=root, capture_output=True,
                                     timeout=payload['candidate_timeout_s'], check=False)
        node_version = subprocess.run(['node', '--version'], cwd=root, capture_output=True,
                                      timeout=payload['candidate_timeout_s'], check=False)
        locked = (tsc_version.returncode == 0 and
                  tsc_version.stdout.strip() == b'Version 5.9.2' and
                  node_version.returncode == 0 and
                  node_version.stdout.strip() == b'v22.21.1')
    except (OSError, subprocess.TimeoutExpired):
        locked = False
    if not locked:
        outcome = {'preflight': result('unavailable', 'toolchain_unavailable'), 'groups': {}}
    else:
        typecheck = run(['tsc', '--noEmit'], payload['candidate_timeout_s'])
        build = (run(['tsc', '--outDir', '/tmp/workflow-build'],
                     payload['candidate_timeout_s'])
                 if typecheck['status'] == 'passed' else typecheck)
        if typecheck['status'] != 'passed':
            outcome = {'preflight': result(typecheck['status'],
                       'typecheck_' + str(typecheck['cause'])), 'groups': {}}
        elif build['status'] != 'passed':
            outcome = {'preflight': result(build['status'],
                       'build_' + str(build['cause'])), 'groups': {}}
        else:
            groups = {}
            for group in payload['groups']:
                groups[group['name']] = run(group['command'], payload['candidate_timeout_s'])
            outcome = {'preflight': result('passed'), 'groups': groups}
sys.stdout.write(json.dumps(outcome, separators=(',', ':')))
"""


class DockerWorkflowRunner(SandboxLifecycle[WorkflowRunnerSettings]):
    """Run the same locked Node toolchain without mounts or network access."""

    def __init__(self, settings: WorkflowRunnerSettings) -> None:
        self.settings = settings
        super().__init__()

    def configuration(self) -> dict[str, Any]:
        return {
            "id": "docker-typescript-functional",
            "version": "1",
            "settings": self.settings.model_dump(mode="json"),
            "harness_sha256": digest_bytes(_HARNESS.encode()),
            "network": "none",
            "dependencies": "locked-image-only",
            "patch_applications": 1,
        }

    async def run(
        self,
        *,
        baseline: Mapping[str, str],
        baseline_tree_digest: str,
        patch: str,
        groups: tuple[WorkflowTestGroup, ...],
    ) -> WorkflowCorrectnessResult:
        def unavailable(cause: str) -> WorkflowCorrectnessResult:
            return WorkflowCorrectnessResult(
                "unavailable",
                tuple(GroupResult(name, "unavailable", cause) for name in GROUP_NAMES),
                cause,
            )

        try:
            tree = validate_repository(baseline)
            if digest_bytes(canonical_json(tree)) != baseline_tree_digest:
                return unavailable("baseline_digest_mismatch")
            if tuple(group.name for group in groups) != GROUP_NAMES:
                return unavailable("invalid_test_groups")
            for group in groups:
                validate_repository(group.files)
                if not group.command or group.command[0] != "node":
                    return unavailable("invalid_test_command")
                if any(path in tree for path in group.files):
                    return unavailable("test_path_collision")
            frozen_paths = [path for group in groups for path in group.files]
            if len(set(frozen_paths)) != len(frozen_paths):
                return unavailable("test_path_collision")
            if not isinstance(patch, str) or not patch:
                return unavailable("invalid_patch")
        except ValueError:
            return unavailable("invalid_input")
        failure = await self._check_runtime()
        if failure is not None:
            return unavailable(failure.error_type)
        payload = canonical_json(
            {
                "baseline": tree,
                "patch": patch,
                "groups": [group.model_dump(mode="json") for group in groups],
                "candidate_timeout_s": self.settings.candidate_timeout_s,
                "max_output_bytes": self.settings.max_output_bytes,
            }
        )
        name = "assay-workflow-correctness-" + uuid.uuid4().hex
        command = (
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
            "/tmp:rw,nosuid,nodev,size=128m",
            "--user",
            "65534:65534",
            "--workdir",
            "/tmp",
            "--entrypoint",
            "python",
            "-i",
            self.settings.image,
            "-I",
            "-S",
            "-c",
            _HARNESS,
        )
        process: asyncio.subprocess.Process | None = None
        stdout = b""
        failure_cause: str | None = None
        try:
            async with asyncio.timeout(self.settings.deadline_s):
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await process.communicate(payload)
                if len(stdout) + len(stderr) > self.settings.max_output_bytes:
                    failure_cause = "output_limit"
                elif process.returncode:
                    failure_cause = "sandbox_process_failed"
        except TimeoutError:
            failure_cause = "infrastructure_deadline"
        except OSError:
            failure_cause = "sandbox_unavailable"
        finally:
            cleanup_ok = await self._finish_cleanup(process, name)
        if not cleanup_ok:
            return unavailable("sandbox_cleanup_failed")
        if failure_cause is not None:
            return unavailable(failure_cause)
        try:
            value = json.loads(stdout)
            preflight = value["preflight"]
            if preflight["status"] != "passed":
                if preflight["status"] not in ("failed", "unavailable"):
                    raise ValueError("invalid preflight status")
                cause = str(preflight["cause"])
                status: Literal["failed", "unavailable"] = preflight["status"]
                group_status: Literal["failed", "unavailable"] = status
                verdict: Verdict = "incorrect" if status == "failed" else "unavailable"
                return WorkflowCorrectnessResult(
                    verdict,
                    tuple(GroupResult(name, group_status, cause) for name in GROUP_NAMES),
                    cause,
                )
            group_values = value["groups"]
            if set(group_values) != set(GROUP_NAMES):
                raise ValueError("missing group")
            results = tuple(
                GroupResult(name, group_values[name]["status"], group_values[name]["cause"])
                for name in GROUP_NAMES
            )
            if any(item.status not in ("passed", "failed", "unavailable") for item in results):
                raise ValueError("invalid group status")
            if any(item.status == "unavailable" for item in results):
                return WorkflowCorrectnessResult("unavailable", results, "group_unavailable")
            if any(item.status == "failed" for item in results):
                cause = (
                    "candidate_timeout"
                    if any(item.cause == "candidate_timeout" for item in results)
                    else "group_failure"
                )
                return WorkflowCorrectnessResult("incorrect", results, cause)
            return WorkflowCorrectnessResult("correct", results)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return unavailable("sandbox_protocol_error")
