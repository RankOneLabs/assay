from __future__ import annotations

import subprocess

import pytest

from oakridge_history import run as runner_module


def test_main_formats_failed_version_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def failed_run(*_args: object) -> None:
        raise subprocess.CalledProcessError(17, ("node", "--version"))

    monkeypatch.setattr(runner_module, "run", failed_run)
    assert runner_module.main(["--oakridge", "/tmp/oakridge"]) == 1
    error = capsys.readouterr().err
    assert error.startswith("oakridge history: Command '")
    assert "node" in error
    assert "Traceback" not in error
