"""Deterministic functional checks inside a tightly bounded Docker container."""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import uuid
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import Field

from assay.canonical import canonical_json, digest_bytes
from assay.execution import EvaluationFailed, EvaluationResult, EvaluationSuccess
from assay.investigations.consistency import CodingTask, parse_candidate_source
from assay.models import EvaluationCoordinate, WireModel
from assay.repository import validate_repository

CORRECTNESS_CATEGORIES = ("incorrect", "correct")
PYTHON_IMAGE = "python@sha256:2be5d3cb08aa616c6e38d922bd7072975166b2de772004f79ee1bae59fe983dc"
TMPFS_SIZE_BYTES = 1_048_576
REPOSITORY_STORAGE_BUDGET_BYTES = TMPFS_SIZE_BYTES * 3 // 4

_CANDIDATE_HARNESS = r"""import importlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile

dumps = json.dumps
loads = json.loads
payload = loads(sys.stdin.read())
root = None
try:
    root = Path(tempfile.mkdtemp(prefix="assay-repository-"))
    repository = payload["repository"]
    target_path = payload["target_path"]
    for raw_path, content in sorted(repository.items()):
        relative = PurePosixPath(raw_path)
        if (relative.is_absolute() or not relative.parts
                or any(part in {"", ".", ".."} for part in relative.parts)):
            raise ValueError("unsafe repository path")
        destination = root.joinpath(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
    target = root.joinpath(*PurePosixPath(target_path).parts)
    target.write_text(repository[target_path] + "\n" + payload["source"], encoding="utf-8")
    source_root = root / "src"
    sys.path[:0] = [str(source_root), str(root)]
    module_parts = list(PurePosixPath(target_path).with_suffix("").parts)
    if module_parts and module_parts[0] == "src":
        module_parts.pop(0)
    if module_parts and module_parts[-1] == "__init__":
        module_parts.pop()
    module_name = ".".join(module_parts) or "candidate"
    importlib.invalidate_caches()
    module = importlib.import_module(module_name)
    implementation = getattr(module, "implement", None)
    if not callable(implementation):
        raise TypeError("implement is not callable")
    actual = implementation(payload["input"])
    result = {"ok": True, "actual": actual}
except BaseException as error:
    result = {"ok": False, "kind": type(error).__name__}
finally:
    if root is not None:
        shutil.rmtree(root, ignore_errors=True)
sys.stdout.write(dumps(result, allow_nan=False, ensure_ascii=False,
                       sort_keys=True, separators=(",", ":")))
"""

_HARNESS_TEMPLATE = r"""import json
import os
import selectors
import subprocess
import sys

dumps = json.dumps
loads = json.loads
candidate_harness = __CANDIDATE_HARNESS__
max_output_bytes = __MAX_OUTPUT_BYTES__
payload = loads(sys.stdin.read())
sys.stderr.write("R")
sys.stderr.flush()
passed = 0
failures = []
for index, case in enumerate(payload["cases"]):
    try:
        child_payload = dumps({
            "repository": payload["repository"],
            "target_path": payload["target_path"],
            "source": payload["source"],
            "input": case["input"],
        }, allow_nan=False, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        child = subprocess.Popen(
            [sys.executable, "-I", "-S", "-c", candidate_harness],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        child.stdin.write(child_payload.encode("utf-8"))
        child.stdin.close()
        selector = selectors.DefaultSelector()
        selector.register(child.stdout, selectors.EVENT_READ, "stdout")
        selector.register(child.stderr, selectors.EVENT_READ, "stderr")
        streams = {"stdout": bytearray(), "stderr": bytearray()}
        exceeded = False
        while selector.get_map():
            for key, _events in selector.select():
                chunk = os.read(key.fileobj.fileno(), 4096)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                streams[key.data].extend(chunk)
                if sum(len(value) for value in streams.values()) > max_output_bytes:
                    exceeded = True
                    child.kill()
                    break
            if exceeded:
                break
        child.wait()
        if exceeded:
            failures.append({"case": index, "kind": "output_limit"})
            continue
        if child.returncode:
            failures.append({"case": index, "kind": "abnormal_exit"})
            continue
        child_result = loads(streams["stdout"].decode("utf-8"))
        if not isinstance(child_result, dict) or child_result.get("ok") is not True:
            kind = child_result.get("kind", "protocol_error")
            if not isinstance(kind, str) or not kind or len(kind) > 100:
                kind = "protocol_error"
            failures.append({"case": index, "kind": kind})
            continue
        actual = child_result["actual"]
        actual_json = dumps(
            actual, allow_nan=False, ensure_ascii=False,
            sort_keys=True, separators=(",", ":"),
        )
        expected_json = dumps(
            case["expected"], allow_nan=False, ensure_ascii=False,
            sort_keys=True, separators=(",", ":"),
        )
        if actual_json == expected_json:
            passed += 1
        else:
            failures.append({"case": index, "kind": "mismatch"})
    except BaseException as error:
        failures.append({"case": index, "kind": type(error).__name__})
result = {"passed": passed, "total": len(payload["cases"]), "failures": failures}
sys.stdout.write(dumps(result, allow_nan=False, sort_keys=True, separators=(",", ":")))
"""

def _render_harness(max_output_bytes: int) -> str:
    return _HARNESS_TEMPLATE.replace(
        "__CANDIDATE_HARNESS__", json.dumps(_CANDIDATE_HARNESS, ensure_ascii=False)
    ).replace("__MAX_OUTPUT_BYTES__", str(max_output_bytes))


class DockerRunnerSettings(WireModel):
    image: Literal[
        "python@sha256:2be5d3cb08aa616c6e38d922bd7072975166b2de772004f79ee1bae59fe983dc"
    ] = "python@sha256:2be5d3cb08aa616c6e38d922bd7072975166b2de772004f79ee1bae59fe983dc"
    platform: Literal["linux/amd64"] = "linux/amd64"
    docker_client_version: Literal["29.6.1"] = "29.6.1"
    docker_server_version: Literal["29.1.2"] = "29.1.2"
    command_timeout_s: float = Field(default=5.0, gt=0, allow_inf_nan=False)
    startup_timeout_s: float = Field(default=10.0, gt=0, allow_inf_nan=False)
    timeout_s: float = Field(default=5.0, gt=0, allow_inf_nan=False)
    max_output_bytes: int = Field(default=65_536, gt=0, strict=True)
    memory: Literal["64m"] = "64m"
    cpus: Literal["0.5"] = "0.5"
    pids_limit: Literal[32] = 32


@dataclasses.dataclass(frozen=True, slots=True)
class SandboxResult:
    passed: int
    total: int
    failures: tuple[dict[str, Any], ...]


@dataclasses.dataclass(frozen=True, slots=True)
class SandboxFailure:
    error_type: str
    message: str


class _OutputLimitExceeded(Exception):
    pass


class DockerPythonRunner:
    """Run untrusted generated code without host mounts, network, or writable root."""

    def __init__(self, settings: DockerRunnerSettings | None = None) -> None:
        self.settings = settings or DockerRunnerSettings()
        self._harness = _render_harness(self.settings.max_output_bytes)
        self._runtime_checked = False
        self._runtime_lock = asyncio.Lock()

    def configuration(self) -> dict[str, Any]:
        return {
            "id": "docker-python-functional",
            "version": "3",
            "settings": self.settings.model_dump(mode="json"),
            "harness_sha256": digest_bytes(self._harness.encode("utf-8")),
            "network": "none",
            "root_filesystem": "read-only",
            "host_mounts": [],
            "capabilities": "drop-all",
            "no_new_privileges": True,
            "seccomp": "builtin",
            "pull": "never",
            "user": "65534:65534",
            "tmpfs": "/tmp:rw,noexec,nosuid,nodev,size=1m",
            "repository_storage_budget_bytes": REPOSITORY_STORAGE_BUDGET_BYTES,
            "ulimits": {"core": "0:0", "fsize": "1048576:1048576", "nofile": "64:64"},
        }

    async def _command(self, *args: str) -> tuple[int, bytes]:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            async with asyncio.timeout(self.settings.command_timeout_s):
                stdout, _ = await process.communicate()
        except TimeoutError as error:
            await self._finish_process(process)
            raise OSError("Docker command timed out") from error
        except asyncio.CancelledError:
            await self._finish_process(process)
            raise
        return process.returncode or 0, stdout

    @staticmethod
    async def _stop_process(process: asyncio.subprocess.Process) -> None:
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(3):
                    await process.wait()

    async def _finish_process(self, process: asyncio.subprocess.Process) -> None:
        closing = asyncio.create_task(self._stop_process(process))
        cancellation: asyncio.CancelledError | None = None
        while not closing.done():
            try:
                await asyncio.shield(closing)
            except asyncio.CancelledError as error:
                cancellation = error
        if cancellation is not None:
            raise cancellation

    async def _check_runtime(self) -> SandboxFailure | None:
        async with self._runtime_lock:
            if self._runtime_checked:
                return None
            try:
                code, versions = await self._command(
                    "docker",
                    "version",
                    "--format",
                    "{{.Client.Version}} {{.Server.Version}}",
                )
                expected = (
                    self.settings.docker_client_version + " " + self.settings.docker_server_version
                )
                if code or versions.decode("ascii").strip() != expected:
                    return SandboxFailure(
                        "SandboxRuntimeMismatch", "Docker runtime version changed"
                    )
                code, _ = await self._command(
                    "docker", "image", "inspect", "--format", "{{.Id}}", self.settings.image
                )
                if code:
                    return SandboxFailure("SandboxImageUnavailable", "pinned image is unavailable")
            except (OSError, UnicodeError):
                return SandboxFailure("SandboxUnavailable", "Docker runtime is unavailable")
            self._runtime_checked = True
            return None

    async def _read_limited(self, stream: asyncio.StreamReader, total: list[int]) -> bytes:
        output = bytearray()
        while chunk := await stream.read(4096):
            output.extend(chunk)
            total[0] += len(chunk)
            if total[0] > self.settings.max_output_bytes:
                raise _OutputLimitExceeded
        return bytes(output)

    async def _remove(self, name: str) -> bool:
        try:
            code, _ = await self._command("docker", "rm", "-f", name)
            if code == 0:
                return True
            check_code, remaining = await self._command(
                "docker", "ps", "-aq", "--filter", f"name=^/{name}$"
            )
            return check_code == 0 and not remaining.strip()
        except OSError:
            return False

    async def _cleanup(self, process: asyncio.subprocess.Process | None, name: str) -> bool:
        try:
            if process is not None and process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                async with asyncio.timeout(3):
                    await process.wait()
        except TimeoutError:
            return False
        return await self._remove(name)

    async def _finish_cleanup(self, process: asyncio.subprocess.Process | None, name: str) -> bool:
        closing = asyncio.create_task(self._cleanup(process, name))
        cancellation: asyncio.CancelledError | None = None
        while not closing.done():
            try:
                await asyncio.shield(closing)
            except asyncio.CancelledError as error:
                cancellation = error
        if cancellation is not None:
            raise cancellation
        return closing.result()

    async def run(
        self,
        *,
        task: CodingTask,
        repository: Mapping[str, str],
        target_path: str,
        source: str,
    ) -> SandboxResult | SandboxFailure:
        try:
            parse_candidate_source(source, helper=task.helper)
        except (SyntaxError, ValueError) as error:
            return SandboxFailure("InvalidOutput", str(error))
        if not task.test_cases:
            return SandboxFailure("InvalidInput", "correctness evaluation requires test cases")
        try:
            validated_repository = validate_repository(repository)
            if target_path != task.target_path or target_path not in validated_repository:
                raise ValueError("target file does not match the governed task")
            per_case_bytes = sum(
                len(content.encode("utf-8")) for content in validated_repository.values()
            ) + len(source.encode("utf-8")) + 1
            if per_case_bytes * len(task.test_cases) > REPOSITORY_STORAGE_BUDGET_BYTES:
                raise ValueError("repository cases exceed the sandbox storage budget")
        except ValueError as error:
            return SandboxFailure("InvalidInput", str(error))
        failure = await self._check_runtime()
        if failure is not None:
            return failure
        payload = canonical_json(
            {
                "repository": validated_repository,
                "target_path": target_path,
                "source": source,
                "cases": [case.model_dump(mode="json") for case in task.test_cases],
            }
        )
        name = "assay-correctness-" + uuid.uuid4().hex
        command = (
            "docker",
            "run",
            "--rm",
            "--name",
            name,
            "--pull=never",
            "--platform",
            self.settings.platform,
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--security-opt=seccomp=builtin",
            "--pids-limit",
            str(self.settings.pids_limit),
            "--memory",
            self.settings.memory,
            "--memory-swap",
            self.settings.memory,
            "--cpus",
            self.settings.cpus,
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=1m",
            "--ulimit",
            "core=0:0",
            "--ulimit",
            "fsize=1048576:1048576",
            "--ulimit",
            "nofile=64:64",
            "--user",
            "65534:65534",
            "--workdir",
            "/tmp",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "-i",
            self.settings.image,
            "python",
            "-I",
            "-S",
            "-c",
            self._harness,
        )
        process: asyncio.subprocess.Process | None = None
        stdout = b""
        candidate_failure: str | None = None
        infrastructure_failure: SandboxFailure | None = None
        ready = False
        try:
            async with asyncio.timeout(self.settings.startup_timeout_s):
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                assert process.stdin is not None
                assert process.stdout is not None
                assert process.stderr is not None
                process.stdin.write(payload)
                await process.stdin.drain()
                process.stdin.close()
                ready = await process.stderr.readexactly(1) == b"R"
            if not ready:
                infrastructure_failure = SandboxFailure(
                    "SandboxStartupFailed", "sandbox harness did not become ready"
                )
            output_total = [0]
            async with asyncio.timeout(self.settings.timeout_s):
                stdout, _stderr, returncode = await asyncio.gather(
                    self._read_limited(process.stdout, output_total),
                    self._read_limited(process.stderr, output_total),
                    process.wait(),
                )
            if returncode:
                if returncode == 125:
                    infrastructure_failure = SandboxFailure(
                        "SandboxProcessFailed", "container runtime rejected execution"
                    )
                else:
                    candidate_failure = "abnormal_exit"
        except TimeoutError:
            if ready:
                candidate_failure = "timeout"
            else:
                infrastructure_failure = SandboxFailure(
                    "SandboxStartupTimeout", "sandbox harness startup timed out"
                )
        except asyncio.IncompleteReadError:
            infrastructure_failure = SandboxFailure(
                "SandboxStartupFailed", "sandbox harness exited before readiness"
            )
        except _OutputLimitExceeded:
            candidate_failure = "output_limit"
        except OSError:
            infrastructure_failure = SandboxFailure(
                "SandboxUnavailable", "sandbox process could not start"
            )
        finally:
            cleanup_ok = await self._finish_cleanup(process, name)
        if not cleanup_ok:
            return SandboxFailure("SandboxCleanupFailed", "sandbox cleanup could not be verified")
        if infrastructure_failure is not None:
            return infrastructure_failure
        if candidate_failure is not None:
            return self._candidate_failure(task, candidate_failure)
        try:
            value = json.loads(stdout)
            if (
                not isinstance(value, dict)
                or set(value) != {"passed", "total", "failures"}
                or type(value["passed"]) is not int
                or type(value["total"]) is not int
                or not isinstance(value["failures"], list)
                or value["total"] != len(task.test_cases)
                or not 0 <= value["passed"] <= value["total"]
            ):
                raise ValueError
            failures = tuple(value["failures"])
            if value["passed"] + len(failures) != value["total"]:
                raise ValueError
            for item in failures:
                if (
                    not isinstance(item, dict)
                    or set(item) != {"case", "kind"}
                    or type(item["case"]) is not int
                    or not 0 <= item["case"] < value["total"]
                    or not isinstance(item["kind"], str)
                    or not item["kind"]
                    or len(item["kind"]) > 100
                ):
                    raise ValueError
            return SandboxResult(value["passed"], value["total"], failures)
        except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError):
            return self._candidate_failure(task, "protocol_error")

    @staticmethod
    def _candidate_failure(task: CodingTask, kind: str) -> SandboxResult:
        failures = tuple({"case": index, "kind": kind} for index in range(len(task.test_cases)))
        return SandboxResult(0, len(task.test_cases), failures)


class FunctionalCorrectnessEvaluator:
    def __init__(self, runner: DockerPythonRunner) -> None:
        self.runner = runner

    def configuration(self) -> dict[str, Any]:
        return {
            "id": "consistency-functional-correctness",
            "version": "3",
            "categories": list(CORRECTNESS_CATEGORIES),
            "runner": self.runner.configuration(),
            "comparison": "canonical-json-output-equality",
            "source_boundary": "optional-docstring-imports-one-implement",
        }

    async def evaluate(
        self, *, input_value: Any, output: Any, coordinate: EvaluationCoordinate
    ) -> EvaluationResult:
        del coordinate
        try:
            task = CodingTask.model_validate(input_value["task"])
            repository = validate_repository(input_value["repository"])
            if task.target_path not in repository:
                raise ValueError("governed target file is missing")
            source = output["source"]
            if not isinstance(source, str):
                raise ValueError("worker output source must be a string")
            parse_candidate_source(source, helper=task.helper)
            if not task.test_cases:
                raise ValueError("correctness evaluation requires test cases")
        except (KeyError, TypeError, ValueError, SyntaxError) as error:
            return EvaluationFailed("InvalidOutput", str(error))
        result = await self.runner.run(
            task=task,
            repository=repository,
            target_path=task.target_path,
            source=source,
        )
        if isinstance(result, SandboxFailure):
            return EvaluationFailed(result.error_type, result.message)
        correct = result.passed == result.total
        detail = {
            "passed_cases": result.passed,
            "total_cases": result.total,
            "failures": list(result.failures),
        }
        return EvaluationSuccess(
            "correct" if correct else "incorrect",
            ("all_cases_passed" if correct else "case_failure",),
            detail,
        )
