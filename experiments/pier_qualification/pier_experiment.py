"""Pier vertical-slice investigation profiles: full, smoke, and qualification.

Every profile is pinned to its own ``RuntimeProfile`` -- distinct runtime
version, image digest, and configuration reference -- so a plan authorized
for one profile can never be silently substituted for another's. Costs are
never hand-typed: every ceiling in this module is
``deterministic_cell_price_estimate``'s output for that profile's exact cell
count at ``PIER_COST_PER_CELL_USD``, checked against the literal numbers this
cohort was specified against in ``pier_qualification/tests/test_pier_profiles.py``.

Preparation (``prepare_*``) never touches a client, a container, or the
network -- it only compiles and publishes a plan from already-declared
subjects/arms/realizations. Execution (``run_*``) additionally requires
``allow_paid=True`` and revalidates the plan's runtime/route/price against
the live adapter immediately before dispatch, mirroring the gating already
established in ``assay.adapters.openrouter_policy`` and the moved DRY
experiment runner.
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import paa_contracts

from assay._version import __version__
from assay.adapters.pier import PierAdapter, PierBridgeClient, worker_configuration
from assay.canonical import canonical_json
from assay.execution import (
    EvaluationFailed,
    Evaluator,
    RunFailed,
    execute_plan,
)
from assay.investigations.consistency import (
    CATEGORIES,
    EXPERIMENT_TASKS,
    CodingTask,
    StructuralEvaluator,
)
from assay.investigations.correctness import (
    CORRECTNESS_CATEGORIES,
    DockerPythonRunner,
    FunctionalCorrectnessEvaluator,
)
from assay.investigations.dry_common import (
    deterministic_arm_price_estimates,
    publish_plan_dependencies,
    repository_for,
)
from assay.investigations.realistic_fixtures import REALISTIC_PILOT_FIXTURES, RepositoryFixture
from assay.models import (
    Arm,
    EvaluatorDeclaration,
    ExecutionPlanV2,
    Realization,
    ReportConfig,
    RuntimeProfile,
    StatisticalProfile,
    StudySnapshot,
    Subject,
)
from assay.pier_protocol import RuntimeBinding
from assay.planning import (
    authorize,
    compile_plan_v2,
    require_runtime_closure,
    validate_plan_snapshot,
)
from assay.report_engine import persist_report
from assay.runtime_inventory import (
    QualificationInventory,
    QualificationRejected,
    load_qualification_inventory,
    runtime_binding_from_inventory,
)
from assay.store import ObjectStore
from assay.verify import export_bundle, reference_closure, verify_bundle, verify_snapshot

PIER_COST_PER_CELL_USD = Decimal("0.72")

# The measured local build digest recorded in integrations/pier/README.md
# ("Runtime identity"): the durable identity input is the lock digest, not
# this image ID, but a fixed, documented value is still pinned here so every
# profile's runtime binding is reproducible rather than invented per call.
PIER_BRIDGE_IMAGE_DIGEST = (
    "sha256:b3e07726d3e92731c1ac1f934d27457a6545a52660af484fd67fb092cf09dc3f"
)

# The exact runtime identity every Pier profile in this cohort is qualified
# against -- integrations/pier/README.md's "Runtime identity"/"Pier revision"
# sections name the Pier PyPI version and mini-swe-agent commit; the lock
# digest is this checkout's own integrations/pier/uv.lock file digest
# (computed once, pinned here exactly like PIER_BRIDGE_IMAGE_DIGEST already
# is); docker_version/uid/gid mirror container.py's actual sandbox identity
# (uid=gid=1000) and the Docker Engine release this cohort's own
# qualification run was performed against. A recorded inventory that does
# not match every one of these exactly is rejected -- not merely
# structurally valid, but the *specific* qualified runtime this cohort's
# profiles are pinned to.
EXPECTED_PIER_REVISION = "0.3.1"
EXPECTED_MINI_SWE_AGENT_REVISION = "a83fcae82d2a08f0ee0c688f9d137b3566c097f8"
EXPECTED_BRIDGE_LOCK_DIGEST = (
    "sha256:d6a23e2601f978add90ee99122580506a458524c25e0151d01ada2d091fc0531"
)
EXPECTED_DOCKER_VERSION = "27.3.1"
EXPECTED_UID = 1000
EXPECTED_GID = 1000

# Two independent, explicit operator decisions a paid run needs beyond
# allow_paid=True -- an env-level approval distinct from the call-level
# allow_paid argument (so a script that always passes allow_paid=True can
# never itself be the thing standing between CI and a paid dispatch), and a
# real, nonblank provider credential in the process environment. Both are
# checked in `_run`, before any plan bytes are even read, so a poison bridge
# standing in for a real PierBridgeClient is never reached for either gate.
PIER_PAID_APPROVAL_ENV = "ASSAY_ALLOW_PAID_PIER"
PIER_PAID_CREDENTIAL_ENV = "OPENROUTER_API_KEY"

# A qualification's own qualified_at timestamp claiming to be from the
# future is untrustworthy on its face -- rejected outright, not merely
# noted. This is deliberately not a rolling "no older than N days" recency
# window: that would make this module's own default golden inventory
# (below) silently start being rejected once enough real time passed,
# purely as a side effect of the calendar rather than any actual staleness
# in the identity it records. How often a qualification must be re-run is
# an operator/deployment cadence decision, not something a vertical-slice
# profile can hardcode without decaying its own fixtures.
_QUALIFICATION_CLOCK_SKEW_TOLERANCE = timedelta(seconds=60)

# The canonical, always-valid qualification ``prepare_pier_*`` defaults to
# when no caller-supplied inventory_ref is given. It matches every
# EXPECTED_* constant exactly and is dated safely in the past, so it never
# fails the not-in-the-future freshness check -- callers who want to
# exercise a different (including a deliberately stale or mismatched)
# inventory pass their own inventory_ref instead.
#
# This default is for local preparation (and tests) only: it asserts
# measured Docker/network/uid/gid properties from constants, not from an
# operator-recorded qualification run. Paid ``run_pier_*`` execution never
# falls back to it -- an omitted ``inventory_ref`` there is a hard error, so
# a real paid run can never be authorized against evidence nobody actually
# measured.
_DEFAULT_QUALIFICATION_INVENTORY = {
    "schema_version": "assay-pier-qualification/0.1.0",
    "bridge": {
        "pier_revision": EXPECTED_PIER_REVISION,
        "mini_swe_agent_revision": EXPECTED_MINI_SWE_AGENT_REVISION,
        "lock_digest": EXPECTED_BRIDGE_LOCK_DIGEST,
        "bridge_image_digest": PIER_BRIDGE_IMAGE_DIGEST,
    },
    "measured": {
        "docker_version": EXPECTED_DOCKER_VERSION,
        "network_none_verified": True,
        "uid": EXPECTED_UID,
        "gid": EXPECTED_GID,
    },
    "qualified_at": "2026-09-11T00:00:00Z",
    "outcome": "succeeded",
}


def _default_qualification_inventory_ref(store: ObjectStore) -> str:
    return str(store.publish_json(_DEFAULT_QUALIFICATION_INVENTORY))


def _validate_qualification_freshness(qualified_at: str) -> None:
    try:
        moment = datetime.fromisoformat(qualified_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(
            f"qualification qualified_at is not a valid ISO-8601 timestamp: {qualified_at!r}"
        ) from error
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    if moment > datetime.now(UTC) + _QUALIFICATION_CLOCK_SKEW_TOLERANCE:
        raise ValueError(f"qualification qualified_at is in the future: {qualified_at!r}")


def _validate_qualification_identity(inventory: QualificationInventory) -> None:
    bridge, measured = inventory.bridge, inventory.measured
    if bridge.pier_revision != EXPECTED_PIER_REVISION:
        raise ValueError("qualification pier_revision does not match the expected pinned revision")
    if bridge.mini_swe_agent_revision != EXPECTED_MINI_SWE_AGENT_REVISION:
        raise ValueError(
            "qualification mini_swe_agent_revision does not match the expected pinned revision"
        )
    if bridge.lock_digest != EXPECTED_BRIDGE_LOCK_DIGEST:
        raise ValueError("qualification lock_digest does not match the expected pinned lock")
    if bridge.bridge_image_digest != PIER_BRIDGE_IMAGE_DIGEST:
        raise ValueError(
            "qualification bridge_image_digest does not match the expected pinned image"
        )
    if measured.docker_version != EXPECTED_DOCKER_VERSION:
        raise ValueError("qualification docker_version does not match the expected pinned version")
    if measured.network_none_verified is not True:
        raise ValueError("qualification did not verify network isolation")
    if measured.uid != EXPECTED_UID or measured.gid != EXPECTED_GID:
        raise ValueError("qualification uid/gid does not match the expected sandbox identity")


def _load_and_validate_inventory(
    store: ObjectStore, *, inventory_ref: str
) -> QualificationInventory:
    """Read, freshness-check, and identity-check a qualification; fails closed.

    Never touches the network or Docker -- ``load_qualification_inventory``
    itself already guarantees that; this only adds the freshness/identity
    checks this cohort's profiles require on top of a structurally valid
    inventory.
    """
    result = load_qualification_inventory(store, inventory_ref=inventory_ref)
    if isinstance(result, QualificationRejected):
        raise ValueError(f"Pier qualification rejected: {result.reason}")
    _validate_qualification_freshness(result.qualified_at)
    _validate_qualification_identity(result)
    return result


PIER_MODEL_ROUTE: Mapping[str, str] = {
    "endpoint": "https://openrouter.ai/api/v1",
    "model": "anthropic/claude-3-haiku",
    "provider": "amazon-bedrock",
}
PIER_TRIAL_LIMITS: Mapping[str, float | int] = {
    "cpu": 1,
    "memory_mb": 1024,
    "pids": 64,
    "timeout_s": 600,
    # A size-capped tmpfs, not an unbounded scratch directory --
    # integrations/pier's container.py enforces this exactly (a real
    # ENOSPC past this ceiling, not merely a declared one); the local
    # qualification script proves that enforcement before this constant is
    # ever trusted for a paid run.
    "storage_mb": 512,
}

ARM_IDS = ("clean", "inconsistent")

# Cost ceilings this cohort was specified against -- literal numbers, checked
# in pier_qualification/tests/test_pier_profiles.py against deterministic_cell_price_estimate's
# derivation from PIER_COST_PER_CELL_USD, never hardcoded independently here.
PIER_FULL_TOTAL_USD = "34.56"
PIER_FULL_PER_ARM_USD = "17.28"
PIER_SMOKE_TOTAL_USD = "2.88"
PIER_SMOKE_PER_ARM_USD = "1.44"
PIER_QUALIFICATION_TOTAL_USD = "11.52"
PIER_QUALIFICATION_PER_ARM_USD = "5.76"


@dataclass(frozen=True)
class PierExperimentPrepared:
    snapshot_ref: str
    plan_ref: str
    cells: int
    evaluations: int


@dataclass(frozen=True)
class PierExperimentFailed:
    error_type: str
    message: str
    manifest_ref: str | None = None
    abstraction_report_ref: str | None = None
    correctness_report_ref: str | None = None


@dataclass(frozen=True)
class PierExperimentSucceeded:
    manifest_ref: str
    abstraction_report_ref: str
    correctness_report_ref: str


@dataclass(frozen=True, slots=True)
class PierCandidateEvaluator:
    """Adapts Pier's ``candidate_ref`` into the ``output["source"]`` string
    shape ``StructuralEvaluator``/``FunctionalCorrectnessEvaluator`` already
    expect, then delegates unchanged -- ``configuration()`` returns exactly
    the wrapped delegate's own configuration, so the declared evaluator
    identity a plan authorizes is the real structural/functional check, not
    a distinct wrapper identity.

    Pier's worker output is a content ref (``candidate_ref``), not raw
    source text: the referenced object is the base64 envelope
    ``_publish_available_artifacts`` wraps every raw artifact in (see
    ``assay.adapters.pier``), so this decodes that envelope back to the
    original bytes before handing plain source text to the delegate.
    """

    store: ObjectStore
    delegate: Evaluator

    def configuration(self) -> dict[str, Any]:
        return self.delegate.configuration()

    async def evaluate(
        self, *, input_value: Any, output: Any, coordinate: Any
    ) -> EvaluationFailed | Any:
        if not isinstance(output, dict) or not isinstance(output.get("candidate_ref"), str):
            return EvaluationFailed("MissingCandidate", "no candidate_ref in worker output")
        try:
            envelope = json.loads(self.store.read_bytes(output["candidate_ref"]))
            source = base64.b64decode(envelope["content_base64"]).decode("utf-8")
        except Exception as error:
            return EvaluationFailed(type(error).__name__, f"could not decode candidate: {error}")
        return await self.delegate.evaluate(
            input_value=input_value, output={"source": source}, coordinate=coordinate
        )


def _publish_runtime(
    store: ObjectStore, *, profile: str, inventory_ref: str
) -> tuple[RuntimeBinding, RuntimeProfile]:
    """One arm-level runtime identity for ``profile``, derived from a qualified inventory.

    The qualified bridge identity (``runtime_version``/``image_digest``) is
    the same across every profile qualified against the same inventory --
    what distinguishes one profile's runtime from another's is its
    configuration (model route, trial limits, and the profile name itself),
    which is why ``configuration_ref`` is still published per profile and
    remains distinct even though the underlying qualified runtime is shared.
    """
    inventory = _load_and_validate_inventory(store, inventory_ref=inventory_ref)
    placeholder_package_digest = "sha256:" + "0" * 64
    configuration = {
        "runtime_id": "pier",
        "runtime_version": inventory.bridge.lock_digest,
        "image_digest": inventory.bridge.bridge_image_digest,
        "model_route": dict(PIER_MODEL_ROUTE),
        "trial_limits": dict(PIER_TRIAL_LIMITS),
        "profile": profile,
    }
    configuration_ref = str(store.publish_json(configuration))
    binding = runtime_binding_from_inventory(
        inventory, configuration_ref=configuration_ref, package_digest=placeholder_package_digest
    )
    runtime = RuntimeProfile(
        id=binding.runtime_id, version=binding.runtime_version, configuration_ref=configuration_ref
    )
    return binding, runtime


def _companion_schema(schema_id: str, categories: tuple[str, ...]) -> dict[str, Any]:
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": schema_id,
        "allOf": [
            {"$ref": "https://paa.dev/paa-evidence-record.schema.json"},
            {"properties": {"verdict": {"properties": {"value": {"enum": list(categories)}}}}},
        ],
    }


def _materialize_pier_snapshot(
    store: ObjectStore,
    *,
    profile: str,
    tasks: Sequence[CodingTask],
    repositories: Mapping[str, Mapping[str, Mapping[str, str]]],
    inventory_ref: str,
    runner: DockerPythonRunner,
) -> tuple[StudySnapshot, RuntimeBinding]:
    """One subject per task, two arms (clean/inconsistent), Pier-shaped realizations."""

    def publish(value: Any) -> str:
        return str(store.publish_json(value))

    binding, _ = _publish_runtime(store, profile=profile, inventory_ref=inventory_ref)
    arm_worker = worker_configuration(
        binding=binding, model_route=PIER_MODEL_ROUTE, trial_limits=PIER_TRIAL_LIMITS
    )
    arms = tuple(
        Arm(id=arm_id, worker=arm_worker, intervention={"repository": arm_id}) for arm_id in ARM_IDS
    )

    subjects = []
    realizations = []
    for task in tasks:
        task_value = task.model_dump(mode="json", exclude={"reused_source", "duplicated_source"})
        subject_ref = publish(task_value)
        subjects.append(
            Subject(
                id=task.id,
                label=task.instruction,
                partition=task.family,
                digest=subject_ref,
                payload_ref=subject_ref,
            )
        )
        for arm_id in ARM_IDS:
            repository = repositories[task.id][arm_id]
            # The full task dict, not just its instruction string: the
            # abstraction/correctness evaluators below need CodingTask's own
            # fields (helper, primitives, test_cases, ...), not merely the
            # instruction text the bridge package renders.
            realization_value = {"task": task_value, "repository": dict(repository)}
            artifact_ref = publish(realization_value)
            realizations.append(
                Realization(
                    subject_id=task.id,
                    arm_id=arm_id,
                    digest=artifact_ref,
                    artifact_ref=artifact_ref,
                )
            )

    abstraction_identity = {
        "property": "abstraction_use",
        "target": "output",
        "technique": "deterministic",
        "evaluation_basis": {
            "kind": "rubric",
            "ref": publish(
                {
                    "categories": list(CATEGORIES),
                    "definition": (
                        "Direct helper reuse; mixed includes calls to any primitive "
                        "used by the helper."
                    ),
                }
            ),
        },
        "epistemic_status": "proxy",
        "version": "1",
        "authority": "advisory",
    }
    abstraction_schema_id = f"https://assay.local/schemas/pier-{profile}-abstraction-v1.json"
    abstraction = EvaluatorDeclaration(
        id="abstraction",
        identity=abstraction_identity,
        payload_schema=abstraction_schema_id,
        payload_schema_ref=publish(_companion_schema(abstraction_schema_id, CATEGORIES)),
        configuration=StructuralEvaluator().configuration(),
        basis_ref=publish({"invariant": "structural abstraction-use classification"}),
        repeats=1,
    )
    correctness_identity = {
        "property": "functional_correctness",
        "target": "output",
        "technique": "deterministic",
        "evaluation_basis": {
            "kind": "invariant",
            "ref": publish(
                {
                    "categories": list(CORRECTNESS_CATEGORIES),
                    "definition": "All hidden deterministic task cases pass in the pinned sandbox.",
                }
            ),
        },
        "epistemic_status": "proxy",
        "version": "1",
        "authority": "advisory",
    }
    correctness_schema_id = f"https://assay.local/schemas/pier-{profile}-correctness-v1.json"
    correctness = EvaluatorDeclaration(
        id="correctness",
        identity=correctness_identity,
        payload_schema=correctness_schema_id,
        payload_schema_ref=publish(
            _companion_schema(correctness_schema_id, CORRECTNESS_CATEGORIES)
        ),
        configuration=FunctionalCorrectnessEvaluator(runner).configuration(),
        basis_ref=publish({"invariant": "finite hidden test-case correctness"}),
        repeats=1,
    )
    task_declaration = {
        "task": f"pier_{profile}",
        "version": 1,
        "description": f"Pier {profile} vertical-slice run",
        "boundary": {"input": "task_repository", "output": "candidate_source"},
        "initial_position": "manual",
        "deployment": "shadow",
        "evaluators": [abstraction_identity, correctness_identity],
        "position_policy": {"manual": "offline", "hitl": "blocking"},
        "promotion": {
            "from": "manual",
            "to": "hitl",
            "report": f"pier_{profile}_report",
            "window": {"kind": "cases", "size": 10},
            "execution": "operator_approval",
        },
        "demotion": {
            "from": "hitl",
            "to": "manual",
            "trigger": "operator_decision",
            "window": {"kind": "cases", "size": 1},
        },
    }
    snapshot = StudySnapshot(
        subjects=tuple(subjects),
        arms=arms,
        realizations=tuple(realizations),
        evaluators=(abstraction, correctness),
        paa_task_ref=publish(task_declaration),
        pricing_catalog_ref=publish({"per_cell_usd": str(PIER_COST_PER_CELL_USD)}),
        task_schema_ref=publish(paa_contracts.load_schema("paa-task")),
        evidence_schema_ref=publish(paa_contracts.load_schema("paa-evidence-record")),
        operating_schema_ref=publish(paa_contracts.load_schema("paa-operating-record")),
    )
    return snapshot, binding


def _repositories_for_tasks(
    tasks: Sequence[CodingTask],
) -> dict[str, dict[str, Mapping[str, str]]]:
    return {
        task.id: {arm_id: repository_for(task, arm_id, None) for arm_id in ARM_IDS}
        for task in tasks
    }


def _repositories_for_fixtures(
    fixtures: Sequence[RepositoryFixture],
) -> dict[str, dict[str, Mapping[str, str]]]:
    return {
        fixture.task.id: {
            "clean": fixture.clean_repository,
            "inconsistent": fixture.inconsistent_repository,
        }
        for fixture in fixtures
    }


def _prepare(
    store: ObjectStore,
    *,
    profile: str,
    tasks: Sequence[CodingTask],
    repositories: Mapping[str, Mapping[str, Mapping[str, str]]],
    worker_repeats: int,
    expected_cells: int,
    inventory_ref: str,
    runner: DockerPythonRunner,
) -> PierExperimentPrepared | PierExperimentFailed:
    try:
        snapshot, _ = _materialize_pier_snapshot(
            store,
            profile=profile,
            tasks=tasks,
            repositories=repositories,
            inventory_ref=inventory_ref,
            runner=runner,
        )
        verify_snapshot(store, snapshot)
        snapshot_ref = str(store.publish_json(snapshot.model_dump(mode="json")))
        publish_plan_dependencies(store, snapshot)
        cells_per_arm = expected_cells // len(ARM_IDS)
        _, runtime = _publish_runtime(store, profile=profile, inventory_ref=inventory_ref)
        plan = compile_plan_v2(
            snapshot,
            snapshot_ref=snapshot_ref,
            worker_repeats=worker_repeats,
            runtime=runtime,
            arm_cost_estimates=deterministic_arm_price_estimates(
                arm_ids=ARM_IDS, cells_per_arm=cells_per_arm, per_cell_usd=PIER_COST_PER_CELL_USD
            ),
        )
        plan_ref = str(store.publish_json(plan.model_dump(mode="json")))
        require_runtime_closure(store, plan)
        reference_closure(store, (plan_ref,))
        if len(plan.cells) != expected_cells:
            raise ValueError(f"unexpected Pier {profile} grid: {len(plan.cells)} cells")
        return PierExperimentPrepared(
            snapshot_ref, plan_ref, len(plan.cells), len(plan.evaluations)
        )
    except Exception as error:
        return PierExperimentFailed(type(error).__name__, str(error))


def prepare_pier_full(
    store: ObjectStore,
    *,
    inventory_ref: str | None = None,
    runner: DockerPythonRunner | None = None,
) -> PierExperimentPrepared | PierExperimentFailed:
    """Twelve subjects, two arms, two repeats: 48 ordered cells, $34.56 ceiling.

    ``inventory_ref`` defaults to this module's own canonical, always-fresh
    qualification when omitted; a caller wanting to prove a stale or
    mismatched qualification is rejected passes their own ref instead.
    ``runner`` only declares the correctness evaluator's configuration here
    -- it is never run at prepare time, so this never touches Docker.
    """
    return _prepare(
        store,
        profile="full",
        tasks=EXPERIMENT_TASKS,
        repositories=_repositories_for_tasks(EXPERIMENT_TASKS),
        worker_repeats=2,
        expected_cells=48,
        inventory_ref=inventory_ref or _default_qualification_inventory_ref(store),
        runner=runner or DockerPythonRunner(),
    )


def prepare_pier_smoke(
    store: ObjectStore,
    *,
    inventory_ref: str | None = None,
    runner: DockerPythonRunner | None = None,
) -> PierExperimentPrepared | PierExperimentFailed:
    """One subject, two arms, two repeats: 4 cells, $2.88 ceiling."""
    tasks = EXPERIMENT_TASKS[:1]
    return _prepare(
        store,
        profile="smoke",
        tasks=tasks,
        repositories=_repositories_for_tasks(tasks),
        worker_repeats=2,
        expected_cells=4,
        inventory_ref=inventory_ref or _default_qualification_inventory_ref(store),
        runner=runner or DockerPythonRunner(),
    )


def prepare_pier_qualification(
    store: ObjectStore,
    *,
    inventory_ref: str | None = None,
    runner: DockerPythonRunner | None = None,
) -> PierExperimentPrepared | PierExperimentFailed:
    """All four realistic-pilot fixtures, two arms, two repeats: 16 cells, $11.52 ceiling."""
    return _prepare(
        store,
        profile="qualification",
        tasks=tuple(fixture.task for fixture in REALISTIC_PILOT_FIXTURES),
        repositories=_repositories_for_fixtures(REALISTIC_PILOT_FIXTURES),
        worker_repeats=2,
        expected_cells=16,
        inventory_ref=inventory_ref or _default_qualification_inventory_ref(store),
        runner=runner or DockerPythonRunner(),
    )


# The exact (total, per-arm) USD ceiling every authorized plan for a profile
# must carry -- checked against the plan itself immediately before dispatch,
# never assumed from how the plan was prepared.
_PROFILE_CEILINGS_USD: Mapping[str, tuple[str, str]] = {
    "full": (PIER_FULL_TOTAL_USD, PIER_FULL_PER_ARM_USD),
    "smoke": (PIER_SMOKE_TOTAL_USD, PIER_SMOKE_PER_ARM_USD),
    "qualification": (PIER_QUALIFICATION_TOTAL_USD, PIER_QUALIFICATION_PER_ARM_USD),
}


def _revalidate_before_dispatch(
    plan: ExecutionPlanV2,
    *,
    profile: str,
    binding: RuntimeBinding,
) -> None:
    """Re-check the plan actually being authorized -- not a value re-derived
    from this call's own arguments -- right before the paid call.

    Two independent facts about ``plan`` are checked here, neither of which
    the earlier ``plan.runtime.version``/``plan_runtime_configuration``
    checks in ``_run`` already cover: that the plan's authorized runtime
    configuration is byte-identical (by content address) to the binding
    dispatch is about to use, and that the plan's declared cost ceilings are
    exactly the profile's published ceiling, not merely internally
    consistent.
    """
    if plan.runtime.configuration_ref != binding.configuration_ref:
        raise ValueError(
            "Pier runtime configuration differs from the plan being authorized"
        )
    total_usd, per_arm_usd = _PROFILE_CEILINGS_USD[profile]
    expected_total = float(Decimal(total_usd))
    expected_per_arm = float(Decimal(per_arm_usd))
    if plan.cost_estimate.amount != expected_total or plan.cost_estimate.currency != "USD":
        raise ValueError("Pier plan total cost ceiling differs from the authorized profile")
    for arm_id, estimate in plan.arm_cost_estimates.items():
        if estimate.amount != expected_per_arm or estimate.currency != "USD":
            raise ValueError(
                f"Pier plan per-arm cost ceiling for {arm_id!r} differs from the authorized profile"
            )


def _pier_report_config(
    manifest_ref: str,
    record_refs: tuple[str, ...],
    *,
    evaluator_id: str,
    categories: tuple[str, ...],
) -> ReportConfig:
    return ReportConfig(
        manifest_refs=(manifest_ref,),
        record_refs=record_refs,
        reference_arm="inconsistent",
        candidates=("clean",),
        evaluator_id=evaluator_id,
        metric="ordinal",
        categories=categories,
        evaluator_repeat_aggregation="median",
        worker_repeat_aggregation="median",
        statistical_profile=StatisticalProfile(seed=7, bootstrap_samples=10_000),
        engine_version=__version__,
    )


async def _run(
    store: ObjectStore,
    *,
    profile: str,
    plan_ref: str,
    authorization: str,
    bridge: PierBridgeClient,
    allow_paid: bool,
    expected_cells: int,
    inventory_ref: str | None = None,
    runner: DockerPythonRunner | None = None,
    export_destination: Path | None = None,
) -> PierExperimentSucceeded | PierExperimentFailed:
    manifest_ref: str | None = None
    abstraction_ref: str | None = None
    correctness_ref: str | None = None
    try:
        if not allow_paid:
            raise ValueError(f"paid Pier {profile} execution requires explicit allow_paid=True")
        if os.environ.get(PIER_PAID_APPROVAL_ENV) != "1":
            raise ValueError(
                f"paid Pier {profile} execution requires {PIER_PAID_APPROVAL_ENV}=1 in the "
                "process environment -- a distinct operator decision from allow_paid=True, "
                "never satisfied by it"
            )
        if not os.environ.get(PIER_PAID_CREDENTIAL_ENV):
            raise ValueError(
                f"paid Pier {profile} execution requires a nonblank {PIER_PAID_CREDENTIAL_ENV} "
                "in the process environment"
            )
        if export_destination is not None and export_destination.exists():
            raise ValueError("export destination already exists")
        plan_bytes = store.read_bytes(plan_ref)
        plan = authorize(plan_bytes, authorization)
        if not isinstance(plan, ExecutionPlanV2):
            raise ValueError("Pier execution requires an assay-execution-plan/0.2.0 plan")
        if plan.runtime.version != EXPECTED_BRIDGE_LOCK_DIGEST:
            raise ValueError("plan is not pinned to the qualified Pier bridge runtime")
        plan_runtime_configuration = json.loads(store.read_bytes(plan.runtime.configuration_ref))
        if plan_runtime_configuration.get("profile") != profile:
            raise ValueError(f"plan is not pinned to the Pier {profile} configuration")
        snapshot = StudySnapshot.model_validate_json(store.read_bytes(plan.snapshot_ref))
        verify_snapshot(store, snapshot)
        validate_plan_snapshot(plan, snapshot)
        require_runtime_closure(store, plan)
        reference_closure(store, (plan_ref,))
        if len(plan.cells) != expected_cells:
            raise ValueError(f"unexpected Pier {profile} grid at execution time")
        if {item.id for item in snapshot.evaluators} != {"abstraction", "correctness"}:
            raise ValueError("Pier experiment evaluator set changed")

        if inventory_ref is None:
            raise ValueError(
                f"paid Pier {profile} execution requires an explicit inventory_ref from a "
                "real recorded qualification -- the synthetic default is for local "
                "preparation only and is never accepted for a paid run"
            )
        binding, _ = _publish_runtime(store, profile=profile, inventory_ref=inventory_ref)
        _revalidate_before_dispatch(plan, profile=profile, binding=binding)
        adapter = PierAdapter(
            store=store,
            bridge=bridge,
            binding=binding,
            model_route=PIER_MODEL_ROUTE,
            trial_limits=PIER_TRIAL_LIMITS,
        )
        runner = runner or DockerPythonRunner()
        runtime_evaluators: dict[str, Evaluator] = {
            "abstraction": PierCandidateEvaluator(store=store, delegate=StructuralEvaluator()),
            "correctness": PierCandidateEvaluator(
                store=store, delegate=FunctionalCorrectnessEvaluator(runner)
            ),
        }
        declared_evaluators = {item.id: item for item in snapshot.evaluators}
        for evaluator_id, evaluator in runtime_evaluators.items():
            if canonical_json(evaluator.configuration()) != canonical_json(
                declared_evaluators[evaluator_id].configuration
            ):
                raise ValueError("Pier evaluator configuration differs from the authorized plan")
        # PierAdapter is a frozen dataclass, so mypy treats its
        # ``supports_cell_coordinates`` attribute as read-only, which the
        # CoordinateAwareWorker protocol's settable-attribute check rejects
        # even though execute_plan only ever reads it at runtime.
        workers: dict[str, Any] = {arm.id: adapter for arm in snapshot.arms}
        result = await execute_plan(
            plan_bytes=plan_bytes,
            authorization=authorization,
            snapshot=snapshot,
            store=store,
            workers=workers,
            evaluators=runtime_evaluators,
        )
        if result.manifest_ref is not None:
            manifest_ref = str(result.manifest_ref)
        if isinstance(result, RunFailed):
            return PierExperimentFailed(
                result.error_type, result.message, manifest_ref, abstraction_ref, correctness_ref
            )
        assert manifest_ref is not None

        by_evaluator: dict[str, tuple[str, ...]] = {}
        for evaluator_id in ("abstraction", "correctness"):
            selected = tuple(
                sorted(
                    str(result.manifest.evaluation_records[coordinate.id])
                    for coordinate in plan.evaluations
                    if coordinate.evaluator_id == evaluator_id
                )
            )
            by_evaluator[evaluator_id] = selected
        abstraction_ref = str(
            persist_report(
                store,
                _pier_report_config(
                    manifest_ref,
                    by_evaluator["abstraction"],
                    evaluator_id="abstraction",
                    categories=CATEGORIES,
                ),
            )
        )
        correctness_ref = str(
            persist_report(
                store,
                _pier_report_config(
                    manifest_ref,
                    by_evaluator["correctness"],
                    evaluator_id="correctness",
                    categories=CORRECTNESS_CATEGORIES,
                ),
            )
        )
        if export_destination is not None:
            if export_destination.exists():
                raise ValueError("export destination already exists")
            abstraction_bundle = export_bundle(
                store, abstraction_ref, export_destination / "abstraction"
            )
            correctness_bundle = export_bundle(
                store, correctness_ref, export_destination / "correctness"
            )
            for bundle, report_ref in (
                (abstraction_bundle, abstraction_ref),
                (correctness_bundle, correctness_ref),
            ):
                failures = verify_bundle(bundle, report_ref)
                if failures:
                    raise ValueError(f"exported bundle failed verification: {failures}")
        return PierExperimentSucceeded(manifest_ref, abstraction_ref, correctness_ref)
    except Exception as error:
        return PierExperimentFailed(
            type(error).__name__, str(error), manifest_ref, abstraction_ref, correctness_ref
        )


async def run_pier_full(
    store: ObjectStore,
    *,
    plan_ref: str,
    authorization: str,
    bridge: PierBridgeClient,
    allow_paid: bool = False,
    inventory_ref: str | None = None,
    runner: DockerPythonRunner | None = None,
    export_destination: Path | None = None,
) -> PierExperimentSucceeded | PierExperimentFailed:
    """Dispatch the ``full`` profile's plan for real, paid execution.

    ``inventory_ref`` must be a real recorded qualification -- unlike
    ``prepare_pier_full``, this never falls back to the synthetic default
    inventory. Omitting it fails the run rather than silently authorizing
    paid dispatch against evidence nobody actually measured.
    """
    return await _run(
        store,
        profile="full",
        plan_ref=plan_ref,
        authorization=authorization,
        bridge=bridge,
        allow_paid=allow_paid,
        expected_cells=48,
        inventory_ref=inventory_ref,
        runner=runner,
        export_destination=export_destination,
    )


async def run_pier_smoke(
    store: ObjectStore,
    *,
    plan_ref: str,
    authorization: str,
    bridge: PierBridgeClient,
    allow_paid: bool = False,
    inventory_ref: str | None = None,
    runner: DockerPythonRunner | None = None,
    export_destination: Path | None = None,
) -> PierExperimentSucceeded | PierExperimentFailed:
    """Dispatch the ``smoke`` profile's plan for real, paid execution.

    ``inventory_ref`` must be a real recorded qualification -- see
    ``run_pier_full``'s docstring for why the synthetic default is never
    accepted here.
    """
    return await _run(
        store,
        profile="smoke",
        plan_ref=plan_ref,
        authorization=authorization,
        bridge=bridge,
        allow_paid=allow_paid,
        expected_cells=4,
        inventory_ref=inventory_ref,
        runner=runner,
        export_destination=export_destination,
    )


async def run_pier_qualification(
    store: ObjectStore,
    *,
    plan_ref: str,
    authorization: str,
    bridge: PierBridgeClient,
    allow_paid: bool = False,
    inventory_ref: str | None = None,
    runner: DockerPythonRunner | None = None,
    export_destination: Path | None = None,
) -> PierExperimentSucceeded | PierExperimentFailed:
    """Dispatch the ``qualification`` profile's plan for real, paid execution.

    ``inventory_ref`` must be a real recorded qualification -- see
    ``run_pier_full``'s docstring for why the synthetic default is never
    accepted here.
    """
    return await _run(
        store,
        profile="qualification",
        plan_ref=plan_ref,
        authorization=authorization,
        bridge=bridge,
        allow_paid=allow_paid,
        expected_cells=16,
        inventory_ref=inventory_ref,
        runner=runner,
        export_destination=export_destination,
    )




__all__ = [
    "ARM_IDS",
    "EXPECTED_BRIDGE_LOCK_DIGEST",
    "EXPECTED_DOCKER_VERSION",
    "EXPECTED_GID",
    "EXPECTED_MINI_SWE_AGENT_REVISION",
    "EXPECTED_PIER_REVISION",
    "EXPECTED_UID",
    "PIER_BRIDGE_IMAGE_DIGEST",
    "PIER_COST_PER_CELL_USD",
    "PIER_FULL_PER_ARM_USD",
    "PIER_FULL_TOTAL_USD",
    "PIER_MODEL_ROUTE",
    "PIER_PAID_APPROVAL_ENV",
    "PIER_PAID_CREDENTIAL_ENV",
    "PIER_QUALIFICATION_PER_ARM_USD",
    "PIER_QUALIFICATION_TOTAL_USD",
    "PIER_SMOKE_PER_ARM_USD",
    "PIER_SMOKE_TOTAL_USD",
    "PIER_TRIAL_LIMITS",
    "PierCandidateEvaluator",
    "PierExperimentFailed",
    "PierExperimentPrepared",
    "PierExperimentSucceeded",
    "prepare_pier_full",
    "prepare_pier_qualification",
    "prepare_pier_smoke",
    "run_pier_full",
    "run_pier_qualification",
    "run_pier_smoke",
]
