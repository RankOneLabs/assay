"""Credential-free acceptance matrix for the Pier integration.

Every test in this module runs in ordinary CI: no ``OPENROUTER_API_KEY``, no
live HTTP, no paid dispatch, no ``allow_paid=True`` call this module's own
code ever authorizes for real. Three kinds of coverage are exercised here,
mirroring the probe categories ``integrations/pier/scripts/qualify_local.py``
gates its qualification inventory on:

- deterministic offline gating logic (every paid profile rejects before it
  ever reaches the bridge boundary, whether ``allow_paid`` is omitted or a
  real qualification inventory is missing);
- local-Docker coverage (the qualification script itself, run end to end
  against the real local Docker daemon when one is reachable -- skipped,
  not faked, when it is not); this exercises the same lock/image identity,
  trial lifecycle, no-reinstall, effective-Docker-controls, artifact
  round-trip, accounting, cancellation, teardown, and orphan probes the
  qualification script itself gates its inventory on -- see
  ``docs/pier-integration.md`` for the walkthrough;
- fake-HTTP coverage of the guarded OpenRouter boundary already lives in
  ``integrations/pier/tests/test_provider.py`` and is exercised again as
  part of the qualification script's own ``probe_fake_boundary``; it is not
  duplicated here.

A paid run against a real provider is never attempted anywhere in this
module, matching the cohort's scope: this suite qualifies and documents the
integration, it does not execute it for money.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from pier_qualification.pier_experiment import (
    PIER_PAID_APPROVAL_ENV,
    PIER_PAID_CREDENTIAL_ENV,
    PierExperimentFailed,
    PierExperimentPrepared,
    prepare_pier_full,
    prepare_pier_qualification,
    prepare_pier_smoke,
    run_pier_full,
    run_pier_qualification,
    run_pier_smoke,
)

from assay.investigations.correctness import DockerPythonRunner
from assay.pier_protocol import PierExchange
from assay.store import ObjectStore

ROOT = Path(__file__).resolve().parents[3]
QUALIFY_SCRIPT = ROOT / "integrations" / "pier" / "scripts" / "qualify_local.py"
_PAID_APPROVAL_ENV = PIER_PAID_APPROVAL_ENV
_PAID_CREDENTIAL_ENV = PIER_PAID_CREDENTIAL_ENV
# Docker server version and the locally-built bridge image's digest are the
# only two measured identities qualify_local.py compares that are
# legitimately host/build-dependent (integrations/pier/README.md flags the
# image digest as explicitly non-reproducible across machines); every other
# comparison (lock digest, pinned revisions, uid/gid, route, trial limits)
# is reproducible from this checkout alone and must always match.
_HOST_DEPENDENT_PROBES = ("docker_available", "image_identity")


def _load_qualify_local() -> ModuleType:
    spec = importlib.util.spec_from_file_location("qualify_local", QUALIFY_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses.dataclass resolves this module's own string annotations
    # (from __future__ import annotations) via sys.modules[cls.__module__]
    # -- it must already be registered there before exec_module runs.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def qualify_local() -> ModuleType:
    return _load_qualify_local()


class _PoisonBridge:
    """A bridge client that fails the test the instant it is asked to dispatch.

    Standing in for a real ``PierBridgeClient`` whose ``create`` would be the
    first thing to ever make an HTTP call. Reaching it before gating rejects
    the run is exactly what "fails before HTTP" must mean, not merely that
    the call eventually raises.
    """

    def create(self, *, exchange: PierExchange, package: Mapping[str, str]) -> Any:
        pytest.fail("paid Pier dispatch reached the bridge boundary before gating rejected it")


_PROFILES = (
    (prepare_pier_smoke, run_pier_smoke),
    (prepare_pier_qualification, run_pier_qualification),
    (prepare_pier_full, run_pier_full),
)


@pytest.mark.parametrize("prepare,run", _PROFILES, ids=["smoke", "qualification", "full"])
async def test_omitted_allow_paid_rejects_before_the_bridge_boundary(
    tmp_path: Path, prepare: Any, run: Any
) -> None:
    store = ObjectStore(tmp_path / ".assay")
    prepared = prepare(store, runner=DockerPythonRunner())
    assert isinstance(prepared, PierExperimentPrepared)

    result = await run(
        store,
        plan_ref=prepared.plan_ref,
        authorization=prepared.plan_ref,
        bridge=_PoisonBridge(),
    )

    assert isinstance(result, PierExperimentFailed)
    assert "allow_paid" in result.message


@pytest.mark.parametrize("prepare,run", _PROFILES, ids=["smoke", "qualification", "full"])
async def test_missing_paid_approval_env_rejects_before_the_bridge_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prepare: Any, run: Any
) -> None:
    """``allow_paid=True`` alone is never enough -- a distinct env-level approval is required too.

    A caller that always passes ``allow_paid=True`` (e.g. a fixed script) must
    still be unable to dispatch for real without an operator separately
    setting ``ASSAY_ALLOW_PAID_PIER=1`` in the process environment.
    """
    monkeypatch.delenv(_PAID_APPROVAL_ENV, raising=False)
    monkeypatch.setenv(_PAID_CREDENTIAL_ENV, "sk-not-a-real-key")
    store = ObjectStore(tmp_path / ".assay")
    prepared = prepare(store, runner=DockerPythonRunner())
    assert isinstance(prepared, PierExperimentPrepared)

    result = await run(
        store,
        plan_ref=prepared.plan_ref,
        authorization=prepared.plan_ref,
        bridge=_PoisonBridge(),
        allow_paid=True,
    )

    assert isinstance(result, PierExperimentFailed)
    assert _PAID_APPROVAL_ENV in result.message


@pytest.mark.parametrize("prepare,run", _PROFILES, ids=["smoke", "qualification", "full"])
async def test_missing_provider_credential_rejects_before_the_bridge_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prepare: Any, run: Any
) -> None:
    """Approval to spend is not a credential to spend with -- both gates are independent."""
    monkeypatch.setenv(_PAID_APPROVAL_ENV, "1")
    monkeypatch.delenv(_PAID_CREDENTIAL_ENV, raising=False)
    store = ObjectStore(tmp_path / ".assay")
    prepared = prepare(store, runner=DockerPythonRunner())
    assert isinstance(prepared, PierExperimentPrepared)

    result = await run(
        store,
        plan_ref=prepared.plan_ref,
        authorization=prepared.plan_ref,
        bridge=_PoisonBridge(),
        allow_paid=True,
    )

    assert isinstance(result, PierExperimentFailed)
    assert _PAID_CREDENTIAL_ENV in result.message

    monkeypatch.setenv(_PAID_CREDENTIAL_ENV, "")
    result = await run(
        store,
        plan_ref=prepared.plan_ref,
        authorization=prepared.plan_ref,
        bridge=_PoisonBridge(),
        allow_paid=True,
    )

    assert isinstance(result, PierExperimentFailed)
    assert _PAID_CREDENTIAL_ENV in result.message


@pytest.mark.parametrize("prepare,run", _PROFILES, ids=["smoke", "qualification", "full"])
async def test_allow_paid_without_a_real_inventory_still_rejects_before_the_bridge_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prepare: Any, run: Any
) -> None:
    from assay.canonical import digest_bytes

    # Both env-level gates satisfied, so this isolates the inventory_ref gate
    # specifically -- proving it is independent of, not shadowed by, either
    # of the other two.
    monkeypatch.setenv(_PAID_APPROVAL_ENV, "1")
    monkeypatch.setenv(_PAID_CREDENTIAL_ENV, "sk-not-a-real-key")
    store = ObjectStore(tmp_path / ".assay")
    prepared = prepare(store, runner=DockerPythonRunner())
    assert isinstance(prepared, PierExperimentPrepared)
    plan_bytes = store.read_bytes(prepared.plan_ref)

    result = await run(
        store,
        plan_ref=prepared.plan_ref,
        authorization=digest_bytes(plan_bytes),
        bridge=_PoisonBridge(),
        allow_paid=True,
    )

    assert isinstance(result, PierExperimentFailed)
    assert "inventory_ref" in result.message


def test_qualify_local_never_reads_or_needs_a_provider_credential() -> None:
    """The qualification script must never read ``OPENROUTER_API_KEY`` itself.

    Every probe it runs is either against the local Docker daemon or a fake
    HTTP transport -- a script that qualifies the runtime for paid execution
    must never itself need, read, or accidentally leak a real credential.
    """
    text = QUALIFY_SCRIPT.read_text(encoding="utf-8")
    assert "os.environ" not in text and "os.getenv" not in text


def _docker_daemon_reachable() -> bool:
    """False for both an unreachable daemon and a missing ``docker`` CLI.

    A bare ``subprocess.run(["docker", ...])`` raises ``FileNotFoundError``
    when the executable itself is absent, which would otherwise blow up
    collection instead of skipping -- exactly the credential-free-suite
    contradiction this helper exists to prevent.
    """
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=10, check=False)
    except FileNotFoundError:
        return False
    return result.returncode == 0


@pytest.mark.skipif(
    not _docker_daemon_reachable(),
    reason="docker daemon is not reachable in this environment",
)
def test_qualify_local_emits_an_inventory_after_every_probe_passes(tmp_path: Path) -> None:
    """End to end against the real local Docker daemon -- with one caveat.

    Docker server version and the built bridge image's digest are the two
    measured identities qualify_local.py compares that are legitimately
    host/build-dependent (see ``_HOST_DEPENDENT_PROBES``); a machine that is
    not the one reference machine ``EXPECTED_DOCKER_VERSION``/
    ``PIER_BRIDGE_IMAGE_DIGEST`` were pinned from can therefore fail here
    for exactly that reason and no other -- still proving every probe up to
    that point ran for real, and that no inventory is published either way.
    """
    output_dir = tmp_path / ".assay-pier-qualification"
    result = subprocess.run(
        [
            sys.executable,
            str(QUALIFY_SCRIPT),
            "--output-dir",
            str(output_dir),
            "--image-tag",
            "assay-pier-bridge:test-acceptance",
        ],
        capture_output=True,
        text=True,
        timeout=600,
        env={**os.environ, "OPENROUTER_API_KEY": ""},
    )
    if result.returncode == 0:
        assert "qualified: sha256:" in result.stdout
        objects = list((output_dir / "objects" / "sha256").iterdir())
        assert objects, "qualify_local.py reported success but published no inventory object"
        return

    combined = result.stdout + result.stderr
    assert any(f"FAIL [{probe}]" in combined for probe in _HOST_DEPENDENT_PROBES), combined
    assert not output_dir.exists(), "a failed qualification must never publish an inventory"


def _raise_qualification_failed(probe: str, module: ModuleType) -> Any:
    def _fail(*args: object, **kwargs: object) -> None:
        raise module.QualificationFailed(probe, "forced failure for a negative test")

    return _fail


_PROBE_ATTRIBUTES = (
    "probe_pinned_revisions",
    "probe_lock_identity",
    "probe_docker_available",
    "probe_image_identity",
    "probe_no_reinstall",
    "probe_trial_lifecycle",
    "probe_storage_enforcement",
    "probe_fake_boundary",
    "_probe_adapter_boundary",
)


@pytest.mark.parametrize("probe_attribute", _PROBE_ATTRIBUTES)
def test_a_failed_probe_never_publishes_an_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    qualify_local: ModuleType,
    probe_attribute: str,
) -> None:
    """Every probe category, forced to fail in isolation, must leave no trace.

    Each of ``qualify_local.py``'s own probes is monkeypatched to fail on
    its own, one at a time, proving the qualification loop actually stops at
    that specific probe (not merely that the script structurally cannot
    reach the inventory-publishing step at all) and that no
    ``QualificationInventory`` -- partial or otherwise -- is ever written.
    """
    monkeypatch.setattr(
        qualify_local, probe_attribute, _raise_qualification_failed(probe_attribute, qualify_local)
    )
    output_dir = tmp_path / ".assay-pier-qualification"

    exit_code = qualify_local.run_qualification(
        output_dir=output_dir, image_tag="assay-pier-bridge:unused-for-this-test"
    )

    assert exit_code == 1
    assert not output_dir.exists(), "a failed probe must never publish an inventory"


@pytest.mark.paid
def test_paid_pier_dispatch_requires_its_own_marker_credentials_and_approval() -> None:
    """Selecting ``-m paid`` alone is not enough to reach a real provider.

    Ordinary CI runs ``pytest -q`` with no marker expression, so this test
    already executes every time; it must still refuse to do anything but
    skip unless an operator has separately set both
    ``ASSAY_ALLOW_PAID_PIER=1`` and a real ``OPENROUTER_API_KEY`` -- and even
    then, this cohort documents preparation through recovery without ever
    performing a paid run, so it fails rather than dispatching regardless.
    """
    if os.environ.get(_PAID_APPROVAL_ENV) != "1" or not os.environ.get(_PAID_CREDENTIAL_ENV):
        pytest.skip(
            f"paid Pier dispatch requires {_PAID_APPROVAL_ENV}=1 and a real "
            f"{_PAID_CREDENTIAL_ENV}; neither is set here, so no HTTP call is ever attempted"
        )
    pytest.fail(
        "a real paid Pier dispatch is out of scope for this cohort even with explicit "
        "operator approval -- see docs/pier-integration.md"
    )
