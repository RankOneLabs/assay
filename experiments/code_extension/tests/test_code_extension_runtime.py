"""A study freezes the host runtime used by its qualified evaluator."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from code_extension.run import _build
from code_extension.tests.test_code_extension_hosted import hosted_configuration

from assay.store import ObjectStore


def test_plan_binds_observed_docker_versions_and_qualified_timeouts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = hosted_configuration()
    version = "29.9.0 29.1.2"

    def docker_version(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert args == ["docker", "version", "--format",
                        "{{.Client.Version}} {{.Server.Version}}"]
        return subprocess.CompletedProcess(args, 0, stdout=version + "\n")

    monkeypatch.setattr("code_extension.qualify.subprocess.run", docker_version)
    monkeypatch.setattr("code_extension.bridge.observed_image_digest",
                        lambda _: config.image_digest)
    first = _build(config, ObjectStore(tmp_path / "first"), live=False)
    settings = first.evaluator.runner.settings
    assert (settings.docker_client_version, settings.docker_server_version) == (
        "29.9.0", "29.1.2",
    )
    assert (settings.candidate_timeout_s, settings.deadline_s) == (60, 300)
    version = "29.9.1 29.1.2"
    second = _build(config, ObjectStore(tmp_path / "second"), live=False)
    assert first.authorization != second.authorization
