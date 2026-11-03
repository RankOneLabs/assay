"""Explicit runtime doubles for tests that replace Docker and provider dispatch."""

from __future__ import annotations

import pytest

from assay.investigations.workflow_correctness import DockerWorkflowRunner, WorkflowRunnerSettings


@pytest.fixture
def qualified_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    def make_runner(image: str) -> DockerWorkflowRunner:
        runner = DockerWorkflowRunner(WorkflowRunnerSettings(
            image=image, toolchain="bun", docker_client_version="test-client",
            docker_server_version="test-server", candidate_timeout_s=60, deadline_s=300,
        ))

        async def check_runtime() -> None:
            return None

        monkeypatch.setattr(runner, "_check_runtime", check_runtime)
        return runner

    monkeypatch.setattr("code_extension.qualify.make_runner", make_runner)
    monkeypatch.setattr("code_extension.diagnose.make_runner", make_runner)
