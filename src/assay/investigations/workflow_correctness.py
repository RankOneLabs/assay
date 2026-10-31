"""Offline TypeScript correctness checks against one declared arm baseline."""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
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
Attribution = Literal["candidate_failure", "evaluator_infrastructure", "unresolved"]
GROUP_NAMES: tuple[GroupName, ...] = (
    "visible_regression",
    "hidden_regression",
    "new_behavior",
)


def workflow_tree_digest(files: Mapping[str, str]) -> str:
    """Match the bridge's regular-tree digest over paths, mode, and file bytes."""
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda value: value.encode("utf-8")):
        digest.update(path.encode("utf-8") + b"\x00100644\x00" + files[path].encode() + b"\x00")
    return f"sha256:{digest.hexdigest()}"


class WorkflowRunnerSettings(WireModel):
    image: Sha256Ref
    toolchain: Literal["node-tsc", "bun"] = "node-tsc"
    expected_versions: dict[str, str] = Field(
        default_factory=lambda: {"tsc": "Version 5.9.3", "node": "v22.21.1", "bun": "1.3.13"}
    )
    docker_client_version: str = "29.6.1"
    docker_server_version: str = "29.1.2"
    command_timeout_s: float = Field(default=5.0, gt=0)
    deadline_s: float = Field(default=120.0, gt=0)
    candidate_timeout_s: float = Field(default=10.0, gt=0)
    max_output_bytes: int = Field(default=131_072, gt=0)


class WorkflowTestGroup(WireModel):
    """Frozen tests copied in after the candidate patch has been applied.

    A ``restores`` group holds the baseline's own visible tests: its files are
    written back over whatever the candidate left at those paths, so editing a
    visible test cannot weaken the regression it is graded against.
    """

    name: GroupName
    files: dict[str, str]
    command: tuple[str, ...]
    restores: bool = False


@dataclasses.dataclass(frozen=True, slots=True)
class GroupResult:
    name: GroupName
    status: Literal["passed", "failed", "unavailable"]
    cause: str | None = None
    stdout: str = ""
    stderr: str = ""
    exit_status: int | None = None
    timeout_s: float | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class PreflightResult:
    status: Literal["passed", "failed", "unavailable"]
    cause: str | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class RejectedChange:
    path: str
    disposition: Literal["restored", "refused"]
    baseline_digest: str | None
    candidate_digest: str | None


@dataclasses.dataclass(frozen=True, slots=True)
class WorkflowCorrectnessResult:
    verdict: Verdict
    groups: tuple[GroupResult, ...]
    cause: str | None = None
    preflight: PreflightResult | None = None
    attribution: Attribution | None = None
    rejected_changes: tuple[RejectedChange, ...] = ()


_CANDIDATE_CAUSES = frozenset({
    "patch_rejected", "build_output_missing", "test_path_collision", "nonzero_exit",
    "candidate_timeout", "output_limit", "group_failure",
})
_INFRASTRUCTURE_CAUSES = frozenset({
    "SandboxImageUnavailable", "SandboxRuntimeMismatch", "SandboxUnavailable",
    "sandbox_process_failed", "sandbox_cleanup_failed", "sandbox_protocol_error",
    "infrastructure_deadline", "toolchain_unavailable", "fixture_asset_unavailable",
    "image_digest_mismatch", "baseline_digest_mismatch", "realization_digest_mismatch",
    "restored_test_mismatch", "invalid_test_groups", "invalid_test_command",
    "missing_test_group", "invalid_patch", "invalid_input",
})


def attribute_cause(cause: str | None) -> Attribution | None:
    if cause is None:
        return None
    if cause in _CANDIDATE_CAUSES or cause.startswith(("typecheck_", "build_")):
        return "candidate_failure"
    if cause in _INFRASTRUCTURE_CAUSES:
        return "evaluator_infrastructure"
    return "unresolved"


_HARNESS = r"""import hashlib
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import sys
import time

payload = json.loads(sys.stdin.buffer.read())
root = Path('/tmp/workflow')
root.mkdir()
for name, source in payload['baseline'].items():
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding='utf-8')

def result(status, cause=None, stdout='', stderr='', exit_status=None, timeout_s=None):
    return {'status': status, 'cause': cause, 'stdout': stdout, 'stderr': stderr,
            'exit_status': exit_status, 'timeout_s': timeout_s}

def run(args, timeout):
    try:
        child = subprocess.Popen(args, cwd=root, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 start_new_session=True)
    except OSError:
        return result('failed', 'toolchain_unavailable')
    selector = selectors.DefaultSelector()
    selector.register(child.stdout, selectors.EVENT_READ, 'stdout')
    selector.register(child.stderr, selectors.EVENT_READ, 'stderr')
    deadline = time.monotonic() + timeout
    streams = {'stdout': bytearray(), 'stderr': bytearray()}
    finished = False
    def capture(status, cause=None, timeout_s=None):
        return result(status, cause, *(bytes(streams[name]).decode('utf-8', 'ignore')
                                      for name in ('stdout', 'stderr')),
                      exit_status=child.poll(), timeout_s=timeout_s)
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return capture('failed', 'candidate_timeout', timeout)
            for key, _events in selector.select(remaining):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                stream = streams[key.data]
                exceeded = len(stream) + len(chunk) > payload['max_output_bytes']
                stream.extend(chunk[:max(0, payload['max_output_bytes'] - len(stream))])
                if exceeded:
                    return capture('failed', 'output_limit')
        try:
            child.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            return capture('failed', 'candidate_timeout', timeout)
        finished = True
        return capture('passed') if child.returncode == 0 else capture('failed', 'nonzero_exit')
    finally:
        selector.close()
        if not finished:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass

def tree_digest(root):
    digest = hashlib.sha256()
    files = []
    for path in root.rglob('*'):
        if path.is_symlink() or (not path.is_file() and not path.is_dir()):
            raise ValueError('candidate tree contains a special path')
        if path.is_file():
            files.append(path)
    for path in sorted(files, key=lambda p: p.relative_to(root).as_posix().encode()):
        name = path.relative_to(root).as_posix().encode()
        digest.update(name + b'\x00100644\x00' + path.read_bytes() + b'\x00')
    return 'sha256:' + digest.hexdigest()

patch = subprocess.run(['git', 'apply', '--allow-empty', '-'], cwd=root,
                       input=payload['patch'].encode('utf-8'),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
candidate_files = {path.relative_to(root).as_posix(): path.read_bytes()
                   for path in root.rglob('*') if path.is_file() and not path.is_symlink()}
baseline_files = {name: source.encode('utf-8') for name, source in payload['baseline'].items()}
restored_paths = {name for group in payload['groups'] if group['restores']
                  for name in group['files']}
protected = {'package.json', 'package-lock.json', 'tsconfig.json'}
rejections = []
for name in sorted(candidate_files.keys() | baseline_files.keys()):
    original, changed = baseline_files.get(name), candidate_files.get(name)
    if original == changed:
        continue
    restore = name in protected or name.startswith('tests/visible/') or name in restored_paths
    if not restore and (not payload['enforce_extension_scope']
                        or name.startswith('src/') or name.startswith('tests/visible/')):
        continue
    rejections.append({'path': name, 'disposition': 'restored' if restore else 'refused',
                       'baseline_digest': 'sha256:' + hashlib.sha256(original).hexdigest()
                       if original is not None else None,
                       'candidate_digest': 'sha256:' + hashlib.sha256(changed).hexdigest()
                       if changed is not None else None})
if patch.returncode:
    outcome = {'preflight': result('failed', 'patch_rejected'), 'groups': {}}
elif tree_digest(root) != payload['expected_tree_digest']:
    outcome = {'preflight': result('unavailable', 'candidate_tree_digest_mismatch'), 'groups': {}}
elif any(group['restores'] for group in payload['groups']) and (
    (root / 'tests' / 'visible').is_file()
    or any(parent.is_file() for group in payload['groups'] if group['restores']
           for name in group['files'] for parent in (root / name).parents)
):
    outcome = {'preflight': result('failed', 'test_path_collision'), 'groups': {}}
elif any(parent.is_file() for group in payload['groups'] for name in group['files']
         for parent in (root / name).parents if parent != root):
    outcome = {'preflight': result('failed', 'test_path_collision'), 'groups': {}}
elif any(item['disposition'] == 'refused' for item in rejections):
    outcome = {'preflight': result('failed', 'patch_rejected'), 'groups': {}}
else:
    for name in protected:
        target = root / name
        if name in baseline_files:
            target.write_bytes(baseline_files[name])
        elif target.exists():
            target.unlink()
    def copy_tests(restores):
        for group in payload['groups']:
            if group['restores'] != restores:
                continue
            for name, source in group['files'].items():
                target = root / name
                if not target.resolve().is_relative_to(root.resolve()):
                    raise ValueError('test path escapes sandbox')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source, encoding='utf-8')

    def reset_visible_tests():
        for name in candidate_files:
            if name.startswith('tests/visible/') and name not in baseline_files:
                (root / name).unlink()
        if payload['enforce_extension_scope'] or any(
            group['restores'] for group in payload['groups']
        ):
            visible = root / 'tests' / 'visible'
            if visible.exists():
                shutil.rmtree(visible)
            for name, source in baseline_files.items():
                if name.startswith('tests/visible/'):
                    target = root / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(source)
            copy_tests(True)

    reset_visible_tests()
    test_paths = [root / name for group in payload['groups']
                  if not group['restores'] for name in group['files']]
    toolchain = payload['toolchain']
    versions = [(['tsc', '--version'], payload['expected_versions']['tsc']),
                (['node', '--version'], payload['expected_versions']['node'])]
    if toolchain == 'bun':
        versions.append((['bun', '--version'], payload['expected_versions']['bun']))
    try:
        locked = True
        for argv, expected in versions:
            observed = subprocess.run(argv, cwd=root, capture_output=True,
                                      timeout=payload['candidate_timeout_s'], check=False)
            locked = locked and observed.returncode == 0 and \
                observed.stdout.strip() == expected.encode()
    except (OSError, subprocess.TimeoutExpired):
        locked = False

    def run_groups():
        return {group['name']: run(group['command'], payload['candidate_timeout_s'])
                for group in payload['groups']}

    if any(target.exists() or any(parent.is_file() for parent in target.parents)
           for target in test_paths):
        outcome = {'preflight': result('failed', 'test_path_collision'), 'groups': {}}
    elif not locked:
        outcome = {'preflight': result('unavailable', 'toolchain_unavailable'), 'groups': {}}
    elif toolchain == 'bun':
        # Frozen visible tests are already restored; hidden tests arrive only
        # after preflight. bun executes TypeScript directly, and bundling every
        # production module is its build check.
        typecheck = run(['tsc', '--noEmit', '-p', 'tsconfig.json'],
                        payload['candidate_timeout_s'])
        sources = sorted(path.relative_to(root).as_posix() for path in root.rglob('*.ts')
                         if path.relative_to(root).parts[0] == 'src'
                         and not path.name.endswith('.test.ts'))
        build = (run(['bun', 'build', '--target=bun', '--outdir', '/tmp/workflow-build',
                      *sources], payload['candidate_timeout_s'])
                 if typecheck['status'] == 'passed' and sources else typecheck)
        if typecheck['status'] != 'passed':
            outcome = {'preflight': result(typecheck['status'],
                       'typecheck_' + str(typecheck['cause'])), 'groups': {}}
        elif not sources:
            outcome = {'preflight': result('failed', 'build_output_missing'), 'groups': {}}
        elif build['status'] != 'passed':
            outcome = {'preflight': result(build['status'],
                       'build_' + str(build['cause'])), 'groups': {}}
        else:
            copy_tests(False)
            outcome = {'preflight': result('passed'), 'groups': run_groups()}
    else:
        typecheck = run(['tsc', '--noEmit'], payload['candidate_timeout_s'])
        build_root = Path('/tmp/workflow-build')
        build = (run(['tsc', '--noEmit', 'false', '--emitDeclarationOnly', 'false',
                      '--outDir', str(build_root)], payload['candidate_timeout_s'])
                 if typecheck['status'] == 'passed' else typecheck)
        if typecheck['status'] != 'passed':
            outcome = {'preflight': result(typecheck['status'],
                       'typecheck_' + str(typecheck['cause'])), 'groups': {}}
        elif build['status'] != 'passed':
            outcome = {'preflight': result(build['status'],
                       'build_' + str(build['cause'])), 'groups': {}}
        elif not any(path.is_file() and path.suffix in ('.js', '.jsx', '.mjs', '.cjs')
                     for path in build_root.rglob('*')):
            outcome = {'preflight': result('failed', 'build_output_missing'), 'groups': {}}
        else:
            copy_tests(False)
            outcome = {'preflight': result('passed'), 'groups': run_groups()}
outcome['rejected_changes'] = rejections
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
        expected_tree_digest: str,
        patch: str,
        groups: tuple[WorkflowTestGroup, ...],
        enforce_extension_scope: bool = False,
    ) -> WorkflowCorrectnessResult:
        def unavailable(
            cause: str, attribution: Attribution | None = None
        ) -> WorkflowCorrectnessResult:
            return WorkflowCorrectnessResult(
                "unavailable",
                tuple(GroupResult(name, "unavailable", cause) for name in GROUP_NAMES),
                cause,
                PreflightResult("unavailable", cause),
                attribution or attribute_cause(cause),
            )

        try:
            tree = validate_repository(baseline)
            if workflow_tree_digest(tree) != baseline_tree_digest:
                return unavailable("baseline_digest_mismatch")
            if tuple(group.name for group in groups) != GROUP_NAMES:
                return unavailable("invalid_test_groups")
            for group in groups:
                validate_repository(group.files)
                runner = "bun" if self.settings.toolchain == "bun" else "node"
                if not group.command or group.command[0] != runner:
                    return unavailable("invalid_test_command")
                if group.restores:
                    # Restored files must be the baseline's own bytes.
                    if any(tree.get(path) != text for path, text in group.files.items()):
                        return unavailable("restored_test_mismatch")
                elif any(path in tree for path in group.files):
                    return unavailable("test_path_collision", "evaluator_infrastructure")
            frozen_paths = [path for group in groups for path in group.files]
            if len(set(frozen_paths)) != len(frozen_paths):
                return unavailable("test_path_collision", "evaluator_infrastructure")
            if not isinstance(patch, str):
                return unavailable("invalid_patch")
        except ValueError:
            return unavailable("invalid_input")
        failure = await self._check_runtime()
        if failure is not None:
            return unavailable(failure.error_type)
        payload = canonical_json(
            {
                "baseline": tree,
                "expected_tree_digest": expected_tree_digest,
                "patch": patch,
                "groups": [group.model_dump(mode="json") for group in groups],
                "candidate_timeout_s": self.settings.candidate_timeout_s,
                "max_output_bytes": self.settings.max_output_bytes,
                "toolchain": self.settings.toolchain,
                "expected_versions": self.settings.expected_versions,
                "enforce_extension_scope": enforce_extension_scope,
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
            "--env",
            "HOME=/tmp",
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
        # json.dumps may expand one captured byte to six ASCII bytes (for example,
        # NUL becomes "\\u0000"). The input allowance covers paths and digest
        # metadata in one rejected-change entry per changed baseline or patch path.
        reply_limit = (
            12 * len(groups) * self.settings.max_output_bytes
            + 8 * len(payload)
            + 256 * (len(tree) + patch.count("\n") + 1)
            + 4096
        )
        try:
            async with asyncio.timeout(self.settings.deadline_s):
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await process.communicate(payload)
                if len(stdout) + len(stderr) > reply_limit:
                    failure_cause = "output_limit"
                elif process.returncode:
                    failure_cause = "sandbox_process_failed"
        except TimeoutError:
            failure_cause = "infrastructure_deadline"
        except OSError:
            failure_cause = "SandboxUnavailable"
        finally:
            cleanup_ok = await self._finish_cleanup(process, name)
        if not cleanup_ok:
            return unavailable("sandbox_cleanup_failed")
        if failure_cause is not None:
            return unavailable(failure_cause)
        try:
            value = json.loads(stdout)
            preflight = value["preflight"]
            rejections = tuple(
                RejectedChange(
                    path=item["path"], disposition=item["disposition"],
                    baseline_digest=item["baseline_digest"],
                    candidate_digest=item["candidate_digest"],
                )
                for item in value.get("rejected_changes", ())
            )
            if any(item.disposition not in ("restored", "refused") for item in rejections):
                raise ValueError("invalid rejection disposition")
            if preflight["status"] != "passed":
                if preflight["status"] not in ("failed", "unavailable"):
                    raise ValueError("invalid preflight status")
                cause = str(preflight["cause"])
                status: Literal["failed", "unavailable"] = preflight["status"]
                attribution = attribute_cause(cause)
                verdict: Verdict = (
                    "incorrect" if status == "failed" and attribution != "unresolved"
                    else "unavailable"
                )
                return WorkflowCorrectnessResult(
                    verdict,
                    tuple(GroupResult(name, "unavailable", cause) for name in GROUP_NAMES),
                    cause,
                    PreflightResult(status, cause),
                    attribution,
                    rejections,
                )
            group_values = value["groups"]
            if set(group_values) != set(GROUP_NAMES):
                raise ValueError("missing group")
            results = tuple(
                GroupResult(
                    name, group_values[name]["status"], group_values[name]["cause"],
                    group_values[name].get("stdout", ""),
                    group_values[name].get("stderr", ""),
                    group_values[name].get("exit_status"),
                    group_values[name].get("timeout_s"),
                )
                for name in GROUP_NAMES
            )
            if any(item.status not in ("passed", "failed", "unavailable") for item in results):
                raise ValueError("invalid group status")
            unknown = next(
                (item.cause for item in results
                 if item.cause is not None and attribute_cause(item.cause) == "unresolved"),
                None,
            )
            if unknown is not None:
                return WorkflowCorrectnessResult(
                    "unavailable", results, unknown, PreflightResult("passed"), "unresolved",
                    rejections,
                )
            if any(item.status == "unavailable" for item in results):
                return WorkflowCorrectnessResult(
                    "unavailable", results, "group_unavailable", PreflightResult("passed"),
                    "evaluator_infrastructure", rejections,
                )
            if any(item.status == "failed" for item in results):
                cause = (
                    "candidate_timeout"
                    if any(item.cause == "candidate_timeout" for item in results)
                    else "group_failure"
                )
                return WorkflowCorrectnessResult(
                    "incorrect", results, cause, PreflightResult("passed"),
                    attribute_cause(cause), rejections,
                )
            return WorkflowCorrectnessResult(
                "correct", results, preflight=PreflightResult("passed"),
                rejected_changes=rejections,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return unavailable("sandbox_protocol_error")
