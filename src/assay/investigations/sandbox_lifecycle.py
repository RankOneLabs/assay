"""Shared Docker command, runtime verification, and cleanup lifecycle."""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
from typing import Protocol


class SandboxSettings(Protocol):
    @property
    def image(self) -> str: ...

    @property
    def docker_client_version(self) -> str: ...

    @property
    def docker_server_version(self) -> str: ...

    @property
    def command_timeout_s(self) -> float: ...


@dataclasses.dataclass(frozen=True, slots=True)
class SandboxFailure:
    error_type: str
    message: str


class SandboxLifecycle[SettingsT: SandboxSettings]:
    settings: SettingsT

    def __init__(self) -> None:
        self._runtime_checked = False
        self._runtime_lock = asyncio.Lock()

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
