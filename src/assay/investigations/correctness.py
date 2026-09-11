"""Deterministic functional checks inside a tightly bounded Docker container."""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import uuid
from typing import Any, Literal

from assay.canonical import canonical_json, digest_bytes
from assay.execution import EvaluationFailed, EvaluationResult, EvaluationSuccess
from assay.investigations.consistency import CodingTask
from assay.models import EvaluationCoordinate, WireModel

CORRECTNESS_CATEGORIES = ("incorrect", "correct")
PYTHON_IMAGE = "python@sha256:2be5d3cb08aa616c6e38d922bd7072975166b2de772004f79ee1bae59fe983dc"

_CANDIDATE_HARNESS = r"""import json
import sys

dumps = json.dumps
loads = json.loads
payload = loads(sys.stdin.read())
try:
    namespace = {"__name__": "candidate"}
    candidate = payload["repository_source"] + "\n" + payload["source"]
    exec(compile(candidate, "<candidate>", "exec"), namespace)
    implementation = namespace.get("implement")
    if not callable(implementation):
        raise TypeError("implement is not callable")
    actual = implementation(payload["input"])
    result = {"ok": True, "actual": actual}
except BaseException as error:
    result = {"ok": False, "kind": type(error).__name__}
sys.stdout.write(dumps(result, allow_nan=False, ensure_ascii=False,
                       sort_keys=True, separators=(",", ":")))
"""

_HARNESS_TEMPLATE = r"""import json
import subprocess
import sys

dumps = json.dumps
loads = json.loads
candidate_harness = __CANDIDATE_HARNESS__
payload = loads(sys.stdin.read())
passed = 0
failures = []
for index, case in enumerate(payload["cases"]):
    try:
        child_payload = dumps({
            "repository_source": payload["repository_source"],
            "source": payload["source"],
            "input": case["input"],
        }, allow_nan=False, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        child = subprocess.run(
            [sys.executable, "-I", "-S", "-c", candidate_harness],
            input=child_payload, text=True, capture_output=True, check=False,
        )
        if len(child.stdout.encode("utf-8")) > 65536 or len(child.stderr.encode("utf-8")) > 65536:
            failures.append({"case": index, "kind": "output_limit"})
            continue
        if child.returncode:
            failures.append({"case": index, "kind": "abnormal_exit"})
            continue
        child_result = loads(child.stdout)
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

_HARNESS = _HARNESS_TEMPLATE.replace(
    "__CANDIDATE_HARNESS__", json.dumps(_CANDIDATE_HARNESS, ensure_ascii=False)
)


class DockerRunnerSettings(WireModel):
    image: str = PYTHON_IMAGE
    platform: Literal["linux/amd64"] = "linux/amd64"
    docker_client_version: Literal["29.6.1"] = "29.6.1"
    docker_server_version: Literal["29.1.2"] = "29.1.2"
    timeout_s: float = 5.0
    max_output_bytes: int = 65_536
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
        self._runtime_checked = False
        self._runtime_lock = asyncio.Lock()

    def configuration(self) -> dict[str, Any]:
        return {
            "id": "docker-python-functional",
            "version": "1",
            "settings": self.settings.model_dump(mode="json"),
            "harness_sha256": digest_bytes(_HARNESS.encode("utf-8")),
            "network": "none",
            "root_filesystem": "read-only",
            "host_mounts": [],
            "capabilities": "drop-all",
            "no_new_privileges": True,
            "seccomp": "builtin",
            "pull": "never",
            "user": "65534:65534",
            "tmpfs": "/tmp:rw,noexec,nosuid,nodev,size=1m",
            "ulimits": {"core": "0:0", "fsize": "1048576:1048576", "nofile": "64:64"},
        }

    async def _command(self, *args: str) -> tuple[int, bytes]:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await process.communicate()
        return process.returncode or 0, stdout

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

    async def _read_limited(self, stream: asyncio.StreamReader) -> bytes:
        output = bytearray()
        while chunk := await stream.read(4096):
            output.extend(chunk)
            if len(output) > self.settings.max_output_bytes:
                raise _OutputLimitExceeded
        return bytes(output)

    async def _remove(self, name: str) -> bool:
        try:
            process = await asyncio.create_subprocess_exec(
                "docker",
                "rm",
                "-f",
                name,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            async with asyncio.timeout(3):
                code = await process.wait()
            if code == 0:
                return True
            check_code, remaining = await self._command(
                "docker", "ps", "-aq", "--filter", f"name=^/{name}$"
            )
            return check_code == 0 and not remaining.strip()
        except (OSError, TimeoutError):
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
        self, *, task: CodingTask, repository_source: str, source: str
    ) -> SandboxResult | SandboxFailure:
        failure = await self._check_runtime()
        if failure is not None:
            return failure
        payload = canonical_json(
            {
                "repository_source": repository_source,
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
            _HARNESS,
        )
        process: asyncio.subprocess.Process | None = None
        stdout = b""
        candidate_failure: str | None = None
        infrastructure_failure: SandboxFailure | None = None
        try:
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
            async with asyncio.timeout(self.settings.timeout_s):
                stdout, _stderr, returncode = await asyncio.gather(
                    self._read_limited(process.stdout),
                    self._read_limited(process.stderr),
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
            candidate_failure = "timeout"
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
            "version": "1",
            "categories": list(CORRECTNESS_CATEGORIES),
            "runner": self.runner.configuration(),
            "comparison": "canonical-json-output-equality",
        }

    async def evaluate(
        self, *, input_value: Any, output: Any, coordinate: EvaluationCoordinate
    ) -> EvaluationResult:
        del coordinate
        try:
            task = CodingTask.model_validate(input_value["task"])
            repository = input_value["repository"]
            if not isinstance(repository, dict) or set(repository) != {"module.py"}:
                raise ValueError("expected one repository module")
            repository_source = repository["module.py"]
            if not isinstance(repository_source, str):
                raise ValueError("repository source must be a string")
            source = output["source"]
            if not isinstance(source, str):
                raise ValueError("worker output source must be a string")
        except (KeyError, TypeError, ValueError) as error:
            return EvaluationFailed("InvalidOutput", str(error))
        result = await self.runner.run(
            task=task, repository_source=repository_source, source=source
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
