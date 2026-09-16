"""Authorized grid execution with durable failure and accounting records."""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from assay.canonical import canonical_json, digest_bytes
from assay.models import (
    CellCoordinate,
    EvaluationCoordinate,
    EvaluationFailure,
    ExecutionOutcome,
    ExecutionPlan,
    ExecutionPlanV2,
    RunManifest,
    StudySnapshot,
)
from assay.planning import authorize, require_runtime_closure, validate_plan_snapshot
from assay.schema_validation import schema_validators
from assay.store import ObjectRef, ObjectStore
from assay.verify import verify_snapshot

type CoverageState = Literal["measured", "estimated", "unavailable", "mixed", "uncertain"]

_COVERAGE_STATES = ("measured", "estimated", "unavailable", "mixed", "uncertain")


@dataclass(frozen=True, slots=True)
class Accounting:
    """Attempt usage, including failed attempts; unavailable prices are never zero.

    ``unavailable`` means the attempt genuinely incurred no priced cost (it was
    never dispatched, or the adapter explicitly has no pricing model).
    ``uncertain`` means the attempt was dispatched but failed before usage or
    price could be observed — the cost is unknown, not zero.
    """

    usage: dict[str, float | None] | None = None
    amount: float | None = None
    currency: str | None = None
    coverage: CoverageState = "unavailable"
    basis: str | None = None

    def __post_init__(self) -> None:
        if self.coverage not in _COVERAGE_STATES:
            raise ValueError("unknown price coverage")
        if self.amount is None:
            if (
                self.coverage not in ("unavailable", "uncertain")
                or self.currency is not None
                or self.basis is not None
            ):
                raise ValueError("unpriced attempt must have no currency or pricing basis")
        elif (
            isinstance(self.amount, bool)
            or not math.isfinite(self.amount)
            or self.amount < 0
            or self.coverage in ("unavailable", "uncertain")
            or not self.currency
            or not self.basis
        ):
            raise ValueError(
                "available price requires finite amount, coverage, currency, and basis"
            )
        if self.usage is not None:
            if not self.usage:
                raise ValueError("use null for unavailable usage")
            for key, value in self.usage.items():
                if not isinstance(key, str) or not key:
                    raise ValueError("usage names must be nonempty strings")
                if value is not None and (
                    isinstance(value, bool)
                    or not isinstance(value, int | float)
                    or not math.isfinite(value)
                    or value < 0
                ):
                    raise ValueError("usage quantities must be finite nonnegative numbers or null")


@dataclass(frozen=True, slots=True)
class WorkerSuccess:
    output: Any
    trace: Any | None = None
    accounting: Accounting = field(default_factory=Accounting)


@dataclass(frozen=True, slots=True)
class WorkerFailure:
    error_type: str
    message: str
    trace: Any | None = None
    accounting: Accounting = field(default_factory=Accounting)


type WorkerResult = WorkerSuccess | WorkerFailure


@dataclass(frozen=True, slots=True)
class EvaluationSuccess:
    verdict: str | float
    reason_codes: tuple[str, ...] = ()
    detail: Any | None = None
    accounting: Accounting = field(default_factory=Accounting)


@dataclass(frozen=True, slots=True)
class EvaluationFailed:
    error_type: str
    message: str
    detail: Any | None = None
    accounting: Accounting = field(default_factory=Accounting)


type EvaluationResult = EvaluationSuccess | EvaluationFailed


class Worker(Protocol):
    def configuration(self, arm_id: str) -> dict[str, Any]: ...

    async def run(self, *, input_value: Any, arm_id: str) -> WorkerResult: ...


class CoordinateAwareWorker(Protocol):
    """A worker that explicitly advertises the immutable-coordinate dispatch path.

    ``supports_cell_coordinates`` must be ``True`` for ``run_cell`` to be used;
    a worker without this attribute (or with it false) is dispatched through
    the structural legacy ``Worker.run`` path instead. This is a deliberate,
    explicit capability flag — never a structural/``hasattr`` guess, and never
    a fallback triggered by catching a ``TypeError`` from a call attempt.
    """

    supports_cell_coordinates: bool

    def configuration(self, arm_id: str) -> dict[str, Any]: ...

    async def run_cell(self, *, input_value: Any, coordinate: CellCoordinate) -> WorkerResult: ...


class AdmissionHalt(Exception):
    """Typed control signal: stop admitting new cells, deterministically.

    Adapters raise this — rather than returning a ``WorkerFailure`` — to
    signal budget exhaustion, identity uncertainty, or billing uncertainty:
    conditions that must stop new dispatch without being mistaken for an
    ordinary per-attempt failure. The cell that raised it still gets a
    definite, recorded outcome; only cells not yet started are affected.
    """

    def __init__(
        self,
        code: Literal["budget_exhausted", "identity_uncertain", "billing_uncertain"],
        message: str,
        *,
        accounting: Accounting | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.accounting = accounting if accounting is not None else Accounting(coverage="uncertain")


def _worker_supports_coordinates(worker: Worker | CoordinateAwareWorker) -> bool:
    return getattr(worker, "supports_cell_coordinates", False) is True


async def _dispatch_worker(
    worker: Worker | CoordinateAwareWorker, *, arm_id: str, cell: CellCoordinate, input_value: Any
) -> WorkerResult:
    """Call the explicitly advertised interface; never probe by catching TypeError."""
    if _worker_supports_coordinates(worker):
        return await worker.run_cell(input_value=input_value, coordinate=cell)  # type: ignore[union-attr]
    return await worker.run(input_value=input_value, arm_id=arm_id)  # type: ignore[union-attr]


class Evaluator(Protocol):
    def configuration(self) -> dict[str, Any]: ...

    async def evaluate(
        self, *, input_value: Any, output: Any, coordinate: EvaluationCoordinate
    ) -> EvaluationResult: ...


@dataclass(frozen=True, slots=True)
class RunSucceeded:
    manifest_ref: ObjectRef
    manifest: RunManifest


@dataclass(frozen=True, slots=True)
class RunFailed:
    error_type: str
    message: str
    manifest: RunManifest | None = None
    manifest_ref: ObjectRef | None = None


type RunResult = RunSucceeded | RunFailed


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


CANCELLATION_CLEANUP_TIMEOUT = 5.0


async def execute_plan(
    *,
    plan_bytes: bytes,
    authorization: str,
    snapshot: StudySnapshot,
    store: ObjectStore,
    workers: dict[str, Worker | CoordinateAwareWorker],
    evaluators: dict[str, Evaluator],
    concurrency: int | None = None,
) -> RunResult:
    """Reject drift before work, and return a recoverable partial manifest on storage failure.

    The adapter configuration methods are a trusted extension boundary: they must
    describe the live settings used by the next call. They are checked both before
    the run and immediately before each attempt.
    """
    try:
        # Wire models contain nested JSON dictionaries; take an owned copy so a
        # caller cannot mutate an authorized declaration while a call is awaiting.
        snapshot = StudySnapshot.model_validate_json(
            canonical_json(snapshot.model_dump(mode="json"))
        )
        workers, evaluators = dict(workers), dict(evaluators)
        plan = authorize(plan_bytes, authorization)
        if not isinstance(plan, ExecutionPlan | ExecutionPlanV2):
            raise ValueError(f"unsupported execution plan type: {type(plan).__name__}")
        snapshot_bytes = canonical_json(snapshot.model_dump(mode="json"))
        if digest_bytes(snapshot_bytes) != plan.snapshot_ref:
            raise ValueError("provided snapshot does not match the authorized plan")
        if store.read_bytes(plan.snapshot_ref) != snapshot_bytes:
            raise ValueError("stored snapshot differs from the provided snapshot")
        validate_plan_snapshot(plan, snapshot)
        verify_snapshot(store, snapshot)
        # A 0.2.0 plan's runtime configuration is a separate closure from the
        # snapshot's; verify_snapshot never walks it, so a caller trusting an
        # authorized V2 plan without this call could run against a runtime
        # configuration that was never fully declared or stored.
        require_runtime_closure(store, plan)
        if plan.preparation_mode != "none":
            raise ValueError("authorized preparation is not implemented")
        if concurrency is not None and concurrency != plan.concurrency:
            raise ValueError("concurrency differs from the authorized plan")
        arms = {arm.id: arm for arm in snapshot.arms}
        declarations = {item.id: item for item in snapshot.evaluators}
        cells = {cell.id: cell for cell in plan.cells}
        for arm in snapshot.arms:
            if canonical_json(workers[arm.id].configuration(arm.id)) != canonical_json(arm.worker):
                raise ValueError(f"worker configuration mismatch: {arm.id}")
        for declaration in snapshot.evaluators:
            store.read_bytes(declaration.basis_ref)
            if canonical_json(evaluators[declaration.id].configuration()) != canonical_json(
                declaration.configuration
            ):
                raise ValueError(f"evaluator configuration mismatch: {declaration.id}")
        # Resolve the complete input/schema closure before any potentially paid call.
        for input_ref in {cell.realization_ref for cell in plan.cells}:
            json.loads(store.read_bytes(input_ref))
        for subject in snapshot.subjects:
            store.read_bytes(subject.payload_ref)
        store.read_bytes(snapshot.pricing_catalog_ref)
        task = json.loads(store.read_bytes(snapshot.paa_task_ref))
        validators = schema_validators(store, snapshot)
        # A plan and configuration used as record references must themselves be durable.
        store.publish_bytes(plan_bytes)
        for arm in snapshot.arms:
            store.publish_json(arm.worker)
            store.publish_json(arm.model_dump(mode="json"))
        for declaration in snapshot.evaluators:
            store.publish_json(declaration.configuration)
            store.publish_json(declaration.model_dump(mode="json"))
        store.publish_json([arm.conditions for arm in snapshot.arms])
    except Exception as error:
        return RunFailed(type(error).__name__, str(error))

    run_id = str(uuid.uuid4())
    execution_records: dict[str, str] = {}
    evaluation_records: dict[str, str] = {}
    operating_records: dict[str, str] = {}
    expected_operating: set[str] = set()
    outputs: dict[str, str] = {}
    fatal: Exception | None = None
    halt: AdmissionHalt | None = None
    unavailable_evaluations: set[str] = set()
    interruption: dict[str, Any] | None = None

    def record_operating(
        *,
        key: str,
        attempt_ref: str,
        accounting: Accounting,
        worker: dict[str, Any],
        configuration: dict[str, Any],
        started_at: str,
        completed_at: str,
    ) -> None:
        if accounting.amount is None:
            if accounting.coverage not in ("unavailable", "uncertain"):
                raise ValueError("missing price must declare unavailable or uncertain coverage")
            price = None
        else:
            if (
                accounting.coverage in ("unavailable", "uncertain")
                or not accounting.currency
                or not accounting.basis
            ):
                raise ValueError("a price requires coverage, currency, and pricing basis")
            price = {
                "amount": accounting.amount,
                "currency": accounting.currency,
                "basis": accounting.basis,
            }
        config_ref = str(store.publish_json(configuration))
        detail_ref = str(
            store.publish_json(
                {
                    "run_id": run_id,
                    "attempt": key,
                    "coverage": accounting.coverage,
                    "pricing_catalog_ref": snapshot.pricing_catalog_ref,
                    "pricing_assumptions": snapshot.pricing_assumptions,
                    "configuration_ref": config_ref,
                }
            )
        )
        record = {
            "record_schema": "paa-operating-record/0.1.0-draft",
            "record_id": f"{run_id}:{key}",
            "task": task["task"],
            "declaration_version": task["version"],
            "scope": snapshot.paa_scope,
            "subject": {"kind": "run", "id": f"{run_id}:{key}"},
            "worker": {**worker, "configuration_ref": config_ref},
            "usage": accounting.usage,
            "price": price,
            "timestamps": {
                "started_at": started_at,
                "completed_at": completed_at,
                "recorded_at": _now(),
            },
            "source_references": list(
                dict.fromkeys(
                    [
                        attempt_ref,
                        detail_ref,
                        snapshot.pricing_catalog_ref,
                        config_ref,
                    ]
                )
            ),
        }
        validators[snapshot.operating_schema_ref].validate(record)
        operating_records[key] = str(store.publish_json(record))

    async def run_cell(cell: CellCoordinate) -> None:
        nonlocal halt
        started_at = _now()
        arm = arms[cell.arm_id]
        attempted = False
        returned = False
        result: WorkerResult = WorkerFailure("NotStarted", "worker was not called")
        try:
            if canonical_json(workers[arm.id].configuration(arm.id)) != canonical_json(arm.worker):
                raise ValueError("worker configuration changed after authorization")
            attempted = True
            result = await _dispatch_worker(
                workers[arm.id],
                arm_id=arm.id,
                cell=cell,
                input_value=json.loads(store.read_bytes(cell.realization_ref)),
            )
            returned = True
            if not isinstance(result, WorkerSuccess | WorkerFailure):
                raise TypeError("worker returned an invalid Result")
            if isinstance(result, WorkerSuccess):
                canonical_json(result.output)
            canonical_json(result.trace)
        except AdmissionHalt as error:
            if halt is None:
                halt = error
            result = WorkerFailure(error.code, error.message, accounting=error.accounting)
        except Exception as error:
            if returned and isinstance(result, WorkerSuccess | WorkerFailure):
                accounting = result.accounting
            elif attempted:
                accounting = Accounting(coverage="uncertain")
            else:
                accounting = Accounting()
            trace = result.trace if isinstance(result, WorkerSuccess | WorkerFailure) else None
            try:
                canonical_json(trace)
            except ValueError:
                trace = None
            result = WorkerFailure(
                type(error).__name__, str(error), trace=trace, accounting=accounting
            )
        completed_at = _now()
        trace_ref = str(store.publish_json(result.trace)) if result.trace is not None else None
        output_ref = None
        if isinstance(result, WorkerSuccess):
            output_ref = str(store.publish_json(result.output))
            outputs[cell.id] = output_ref
        outcome = ExecutionOutcome(
            coordinate=cell,
            run_id=run_id,
            plan_ref=authorization,
            started_at=started_at,
            completed_at=completed_at,
            status="succeeded" if isinstance(result, WorkerSuccess) else "failed",
            input_ref=cell.realization_ref,
            output_ref=output_ref,
            trace_ref=trace_ref,
            error_type=result.error_type if isinstance(result, WorkerFailure) else None,
            error_message=result.message if isinstance(result, WorkerFailure) else None,
        )
        attempt_ref = str(store.publish_json(outcome.model_dump(mode="json")))
        execution_records[cell.id] = attempt_ref
        expected_operating.add(f"worker:{cell.id}")
        record_operating(
            key=f"worker:{cell.id}",
            attempt_ref=attempt_ref,
            accounting=result.accounting,
            worker={"id": arm.worker["id"], "version": arm.worker["version"]},
            configuration=arm.worker,
            started_at=started_at,
            completed_at=completed_at,
        )

    async def run_evaluation(coordinate: EvaluationCoordinate) -> None:
        started_at = _now()
        cell = cells[coordinate.cell_id]
        declaration = declarations[coordinate.evaluator_id]
        output = outputs.get(cell.id)
        attempted = output is not None
        result: EvaluationResult = EvaluationFailed("NotStarted", "evaluator was not called")
        if output is None:
            result = EvaluationFailed("ExecutionUnavailable", "worker execution did not succeed")
            unavailable_evaluations.add(coordinate.id)
        else:
            called = False
            returned = False
            try:
                if canonical_json(evaluators[declaration.id].configuration()) != canonical_json(
                    declaration.configuration
                ):
                    raise ValueError("evaluator configuration changed after authorization")
                called = True
                result = await evaluators[declaration.id].evaluate(
                    input_value=json.loads(store.read_bytes(cell.realization_ref)),
                    output=json.loads(store.read_bytes(output)),
                    coordinate=coordinate,
                )
                returned = True
                if not isinstance(result, EvaluationSuccess | EvaluationFailed):
                    raise TypeError("evaluator returned an invalid Result")
                canonical_json(result.detail)
            except Exception as error:
                if returned and isinstance(result, EvaluationSuccess | EvaluationFailed):
                    accounting = result.accounting
                elif called:
                    accounting = Accounting(coverage="uncertain")
                else:
                    accounting = Accounting()
                result = EvaluationFailed(type(error).__name__, str(error), accounting=accounting)
        completed_at = _now()
        detail_ref = str(store.publish_json(result.detail)) if result.detail is not None else None
        if isinstance(result, EvaluationSuccess):
            assert output is not None
            arm = arms[cell.arm_id]
            config_ref = digest_bytes(canonical_json(arm.worker))
            record: dict[str, Any] = {
                "record_schema": "paa-evidence-record/0.3.0-draft",
                "record_id": f"{run_id}:{coordinate.id}",
                "task": task["task"],
                "declaration_version": task["version"],
                "scope": snapshot.paa_scope,
                "subject": {"kind": "run", "id": f"{run_id}:{cell.id}"},
                "boundary": {"input_ref": cell.realization_ref, "output_ref": output},
                "evaluator": declaration.identity,
                "verdict": {"value": result.verdict, "reason_codes": list(result.reason_codes)},
                "worker": {
                    "id": arm.worker["id"],
                    "version": arm.worker["version"],
                    "configuration_ref": config_ref,
                },
                "producer": {"id": "assay", "version": plan.assay_version},
                "timestamps": {
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "recorded_at": _now(),
                },
                "source_references": list(
                    dict.fromkeys(
                        [
                            execution_records[cell.id],
                            snapshot.paa_task_ref,
                            config_ref,
                            declaration.basis_ref,
                            *([detail_ref] if detail_ref else []),
                        ]
                    )
                ),
                "payload_schema": declaration.payload_schema,
                "payload": {
                    "run_id": run_id,
                    "cell_id": cell.id,
                    "evaluator_id": declaration.id,
                    "plan_ref": authorization,
                    "arm_id": cell.arm_id,
                    "base_subject_ref": next(
                        s.digest for s in snapshot.subjects if s.id == cell.subject_id
                    ),
                    "worker_repeat": cell.worker_repeat,
                    "evaluator_repeat": coordinate.evaluator_repeat,
                    "detail_refs": [detail_ref] if detail_ref else [],
                },
            }
            try:
                canonical_json(record)
                validators[snapshot.evidence_schema_ref].validate(record)
                validators[declaration.payload_schema_ref].validate(record)
            except Exception as error:
                result = EvaluationFailed(
                    "InvalidVerdict", str(error), detail=result.detail, accounting=result.accounting
                )
        if isinstance(result, EvaluationFailed):
            record = EvaluationFailure(
                coordinate=coordinate,
                run_id=run_id,
                plan_ref=authorization,
                started_at=started_at,
                completed_at=completed_at,
                trace_ref=detail_ref,
                error_type=result.error_type,
                error_message=result.message,
            ).model_dump(mode="json")
        attempt_ref = str(store.publish_json(record))
        evaluation_records[coordinate.id] = attempt_ref
        if attempted:
            expected_operating.add(f"evaluator:{coordinate.id}")
            record_operating(
                key=f"evaluator:{coordinate.id}",
                attempt_ref=attempt_ref,
                accounting=result.accounting,
                worker={"id": declaration.id, "version": declaration.identity["version"]},
                configuration=declaration.configuration,
                started_at=started_at,
                completed_at=completed_at,
            )

    async def _drain(tasks: list[asyncio.Task[None]]) -> dict[str, Any] | None:
        """Bounded shield: give active adapter cleanup a fixed window, never an unbounded one.

        Returns a typed cleanup-interruption record when the window elapses
        with tasks still outstanding, so that a durable trace of the
        incomplete cleanup survives even though the tasks themselves were
        abandoned; returns ``None`` when every task drained in time.
        """
        for child in tasks:
            child.cancel()
        # asyncio.gather()'s cancel() only forwards to its children and does
        # not settle until they finish, so wrapping it in wait_for cannot
        # bound a child that swallows its own cancellation: wait_for's timer
        # cancels the *task*, which is the same forward-and-wait-for-real
        # non-resolution. asyncio.wait()'s own timeout is a plain, immediate
        # timer on its internal waiter, independent of child cooperation, so
        # it is the one primitive here that is genuinely bounded.
        _done, pending = await asyncio.wait(tasks, timeout=CANCELLATION_CLEANUP_TIMEOUT)
        if not pending:
            return None
        return {
            "schema_version": "assay-cleanup-interruption/0.1.0",
            "run_id": run_id,
            "reason": "cleanup_timeout",
            "timeout_seconds": CANCELLATION_CLEANUP_TIMEOUT,
            "outstanding_tasks": len(pending),
            "total_tasks": len(tasks),
            "occurred_at": _now(),
        }

    async def bounded[T](
        items: Iterable[T], call: Callable[[T], Awaitable[None]], *, should_stop: Callable[[], bool]
    ) -> None:
        """Only active slots start; a stop signal halts new dispatch, active calls still drain."""
        nonlocal interruption
        iterator = iter(items)

        async def consume() -> None:
            nonlocal fatal
            while not should_stop():
                try:
                    item = next(iterator)
                except StopIteration:
                    return
                try:
                    await call(item)
                except Exception as error:
                    if fatal is None:
                        fatal = error

        tasks = [asyncio.create_task(consume()) for _ in range(plan.concurrency)]
        try:
            # asyncio.gather() forwards cancellation to its children but will
            # not settle -- and so will not deliver that cancellation back to
            # us -- until every child actually finishes, which is exactly the
            # unbounded hang this shield exists to prevent. asyncio.wait()'s
            # internal waiter is cancelled immediately instead, so our own
            # cancellation reaches us right away and _drain gets a genuine
            # chance to bound however long the children take to react to it.
            await asyncio.wait(tasks)
            # asyncio.wait() never raises for a child that finishes cancelled
            # or errored on its own -- e.g. a worker's internal timeout
            # self-cancelling without any external task.cancel(). Surface
            # that here so it still reaches the drain/interruption path
            # below instead of letting execute_plan silently report success
            # with the unfinished work dropped.
            for task in tasks:
                if task.cancelled():
                    raise asyncio.CancelledError()
                error = task.exception()
                if error is not None:
                    raise error
        except BaseException:
            record = await _drain(tasks)
            if record is not None and interruption is None:
                interruption = record
            raise

    def _build_manifest() -> RunManifest:
        expected = set(cells) | {item.id for item in plan.evaluations}
        missing = tuple(
            sorted(
                (expected - execution_records.keys() - evaluation_records.keys())
                | (expected_operating - operating_records.keys())
                | unavailable_evaluations
            )
        )
        interruption_ref = (
            str(store.publish_json(interruption)) if interruption is not None else None
        )
        return RunManifest(
            run_id=run_id,
            plan_ref=authorization,
            status="complete" if not missing and fatal is None and halt is None else "incomplete",
            execution_records=execution_records,
            evaluation_records=evaluation_records,
            operating_records=operating_records,
            missing_coordinates=missing,
            interruption_ref=interruption_ref,
        )

    try:
        await bounded(
            plan.cells, run_cell, should_stop=lambda: fatal is not None or halt is not None
        )
        if fatal is None:
            await bounded(plan.evaluations, run_evaluation, should_stop=lambda: fatal is not None)
    except asyncio.CancelledError:
        # Cancellation stays observable to the caller, but whatever recoverable
        # evidence exists (including cleanup's own typed interruption record,
        # if the bounded shield above did not finish in time) gets a bounded,
        # best-effort chance to become durable incomplete-manifest evidence
        # before cancellation is re-raised.
        with contextlib.suppress(Exception):
            store.publish_json(_build_manifest().model_dump(mode="json"))
        raise

    manifest = _build_manifest()
    try:
        ref = store.publish_json(manifest.model_dump(mode="json"))
    except Exception as error:
        return RunFailed(type(error).__name__, str(error), manifest=manifest)
    terminal = fatal or halt
    if terminal is not None:
        return RunFailed(
            type(terminal).__name__, str(terminal), manifest=manifest, manifest_ref=ref
        )
    return RunSucceeded(ref, manifest)
