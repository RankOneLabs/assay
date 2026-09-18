"""Map a ``TrialRequest`` onto the real, pinned ``pier`` package's config.

``datacurve-pier`` (PyPI, pinned exactly in ``pyproject.toml``/``uv.lock``) is
the real Pier package: its ``pier.trial.trial.Trial.create(config)`` classmethod
is the literal API the "call Trial.create exactly once" key decision names.
This module builds that ``config`` from our closed wire contracts and writes
the on-disk task directory Pier's ``Task`` loader expects.

What this module deliberately does not attempt: driving Pier's own
``EnvironmentFactory`` (docker/modal/daytona) end to end. That factory builds
its container from an ``environment/Dockerfile`` inside the task directory —
a second, independent image-build surface from the one this project already
locked in ``integrations/pier/Dockerfile`` (see ``container.py``). Reconciling
the two — one task-owned image per Pier's model, or one bridge image reused
across tasks per this project's model — is a real design decision, not a
detail, and is recorded as a ``known_issue`` rather than guessed at here.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path

from pier.models.agent.name import AgentName
from pier.models.environment_type import EnvironmentType
from pier.models.task.config import NetworkMode
from pier.models.trial.config import (
    AgentConfig,
    EnvironmentConfig,
    TaskConfig,
    TrialConfig,
    VerifierConfig,
)

from assay_pier_bridge.paths import materialize_under
from assay_pier_bridge.protocol import TrialRequest

WORKSPACE_PREFIX = "workspace"


def sanitized_trial_name(cell_id: str) -> str:
    """Pier trial names are filesystem directory names; ``cell_id`` has colons.

    A local reimplementation of ``assay.pier_protocol.trial_name_for``, and
    injective for the same reason: a plain ``cell_id.replace(":", "-")`` is
    not, because an identifier may itself contain hyphens, so
    ``("a-b", "c")`` and ``("a", "b-c")`` would both normalize to
    ``a-b-c-w0`` and two distinct cells would share one trial directory on
    disk. Doubling every hyphen inside the subject and arm components
    before joining on a single, un-doubled hyphen keeps a lone hyphen in the
    result always a field separator.

    The root project pins both implementations to the same expected outputs
    in ``tests/fixtures/pier_wire_contract.json``.
    """
    parts = cell_id.split(":")
    if len(parts) != 3:
        raise ValueError(f"cell id is not <subject>:<arm>:w<repeat>: {cell_id}")
    subject_id, arm_id, repeat = parts
    return f"{subject_id.replace('-', '--')}-{arm_id.replace('-', '--')}-{repeat}"


def build_trial_config(
    request: TrialRequest,
    *,
    task_dir: Path,
    trials_dir: Path,
) -> TrialConfig:
    """Build the real ``pier`` ``TrialConfig`` for one guarded trial.

    Verification is disabled by construction via the trial-level
    ``VerifierConfig.disable`` override — Assay is the sole scoring
    authority, per the "upstream verification disabled" key decision,
    regardless of whatever a task.toml on disk might otherwise declare. The
    agent phase runs with ``network_mode=NO_NETWORK`` (Pier does not support
    an allowlist mode — see the module docstring); the guarded OpenRouter
    call is made by this bridge process itself, outside the agent's
    sandbox, not by the agent reaching the network directly.
    """
    return TrialConfig(
        task=TaskConfig(path=task_dir),
        trial_name=sanitized_trial_name(request.cell_id),
        trials_dir=trials_dir,
        agent=AgentConfig(
            name=AgentName.MINI_SWE_AGENT.value,
            model_name=request.model_route.model,
            override_timeout_sec=request.limits.timeout_s,
            max_timeout_sec=request.limits.timeout_s,
            kwargs={"provider": request.model_route.provider},
        ),
        environment=EnvironmentConfig(
            type=EnvironmentType.DOCKER,
            # Round down, never up: granting ceil(1.5) == 2 CPUs would exceed
            # what TrialLimits.cpu actually authorized.
            override_cpus=max(1, math.floor(request.limits.cpu)),
            override_memory_mb=request.limits.memory_mb,
        ),
        verifier=VerifierConfig(disable=True),
    )


def write_task_directory(
    task_dir: Path,
    *,
    instruction: str,
    repository: Mapping[str, str],
) -> None:
    """Write the on-disk task directory Pier's ``Task`` loader expects.

    Only ``task.toml`` and ``instruction.md`` are Pier's own contract; the
    repository is written under ``workspace/`` to match this project's
    sealed-package layout (``assay.pier_packaging``), not a documented Pier
    convention — Pier's own ``environment/Dockerfile`` decides what the
    agent actually sees inside its container, which is exactly the
    reconciliation gap the module docstring records.
    """
    if task_dir.exists():
        raise ValueError(
            f"task directory already exists, refusing to reuse it: {task_dir}"
        )
    task_dir.mkdir(parents=True)
    (task_dir / "task.toml").write_text(
        'schema_version = "1.2"\n\n'
        "[agent]\n"
        f'network_mode = "{NetworkMode.NO_NETWORK.value}"\n\n'
        "[environment]\n"
        f'network_mode = "{NetworkMode.NO_NETWORK.value}"\n',
        encoding="utf-8",
    )
    (task_dir / "instruction.md").write_text(instruction, encoding="utf-8")
    materialize_under(task_dir / WORKSPACE_PREFIX, repository)


__all__ = ["build_trial_config", "sanitized_trial_name", "write_task_directory"]
