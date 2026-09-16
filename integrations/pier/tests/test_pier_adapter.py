"""Proves the config/task-directory mapping against the real, pinned pier
package — not a fake. A passing test here means the real ``TrialConfig`` and
``Task`` pydantic/loader code accepted what this bridge builds."""

from __future__ import annotations

from pathlib import Path

from assay_pier_bridge.pier_adapter import (
    build_trial_config,
    sanitized_trial_name,
    write_task_directory,
)
from assay_pier_bridge.protocol import ModelRoute, TrialLimits, TrialRequest
from pier.models.environment_type import EnvironmentType
from pier.models.task.task import Task

ROUTE = ModelRoute(
    endpoint="https://openrouter.ai/api/v1",
    model="anthropic/claude-3-haiku",
    provider="amazon-bedrock",
)


def _request(**overrides: object) -> TrialRequest:
    base = dict(
        cell_id="s1:a1:w0",
        package_digest="sha256:" + "0" * 64,
        model_route=ROUTE,
        limits=TrialLimits(cpu=1.5, memory_mb=512, pids=32, timeout_s=120),
    )
    base.update(overrides)
    return TrialRequest.model_validate(base)


def test_sanitized_trial_name_has_no_colons() -> None:
    assert sanitized_trial_name("s1:a1:w0") == "s1-a1-w0"


def test_build_trial_config_is_accepted_by_the_real_pier_pydantic_model(tmp_path: Path) -> None:
    config = build_trial_config(
        _request(), task_dir=tmp_path / "task", trials_dir=tmp_path / "trials"
    )

    assert config.trial_name == "s1-a1-w0"
    assert config.agent.name == "mini-swe-agent"
    assert config.agent.model_name == "anthropic/claude-3-haiku"
    assert config.environment.type == EnvironmentType.DOCKER
    assert config.environment.override_cpus == 2  # ceil(1.5)
    assert config.environment.override_memory_mb == 512
    # Verification is disabled by construction, regardless of task.toml.
    assert config.verifier.disable is True


def test_written_task_directory_loads_as_a_real_pier_task(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    write_task_directory(
        task_dir,
        instruction="# Task\n\nsay hi\n",
        repository={"solution.py": "print('hi')\n"},
    )

    task = Task(task_dir=task_dir)

    assert task.instruction == "# Task\n\nsay hi\n"
    assert (task_dir / "workspace" / "solution.py").read_text(encoding="utf-8") == "print('hi')\n"
