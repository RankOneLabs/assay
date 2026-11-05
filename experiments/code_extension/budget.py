"""Per-request reservations and durable attempt identities for extension runs."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, TypeVar

from assay_pier_bridge.agent_loop import (
    HAIKU_TURN_ROUTE,
    BilledResponseError,
    ModelTurn,
    OpenRouterTurnRoute,
    _json_bytes,
)
from verification_pilot.budget import BudgetedAgentClient, SpendGate, request_cost_bound

from assay.canonical import canonical_json

T = TypeVar("T")


class AttemptAlreadyUsed(ValueError):
    """A durable attempt identity cannot be dispatched twice."""


class ConfigurationChanged(ValueError):
    """Resume requires the original frozen configuration."""


@dataclass
class AttemptJournal:
    """Append-only fsynced records, one identity per coordinate and attempt."""

    path: Path
    plan_digest: str
    config_digest: str

    def records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_bytes().splitlines() if line]

    def _append(self, record: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("ab") as stream:
            stream.write(canonical_json(record) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        directory_fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def validate_resume(self) -> None:
        for record in self.records():
            if record["plan_digest"] != self.plan_digest:
                raise ConfigurationChanged("resume plan digest differs from frozen plan")
            if record["config_digest"] != self.config_digest:
                raise ConfigurationChanged(
                    "resume configuration digest differs; prepare a new plan"
                )

    def begin(self, coordinate: str, attempt_id: str, bound: Decimal) -> None:
        self.validate_resume()
        if any(
            record.get("attempt_id") == attempt_id and record["event"] == "reserved"
            for record in self.records()
        ):
            raise AttemptAlreadyUsed(f"attempt identity already dispatched: {attempt_id}")
        self._append(
            {
                "event": "reserved",
                "coordinate": coordinate,
                "attempt_id": attempt_id,
                "bound_usd": str(bound),
                "plan_digest": self.plan_digest,
                "config_digest": self.config_digest,
            }
        )

    def claim_attempt(self, coordinate: str, attempt_id: str) -> None:
        """Persist the cell identity before the worker can create a job."""
        self.validate_resume()
        if any(record.get("attempt_id") == attempt_id for record in self.records()):
            raise AttemptAlreadyUsed(f"attempt identity already used: {attempt_id}")
        self._append(
            {
                "event": "attempt_started",
                "coordinate": coordinate,
                "attempt_id": attempt_id,
                "plan_digest": self.plan_digest,
                "config_digest": self.config_digest,
            }
        )

    def finish(self, attempt_id: str, *, cost: Decimal | None, status: str) -> None:
        self.validate_resume()
        self._append(
            {
                "event": "finished",
                "attempt_id": attempt_id,
                "cost_usd": str(cost) if cost is not None else None,
                "status": status,
                "plan_digest": self.plan_digest,
                "config_digest": self.config_digest,
            }
        )

    def record_probe_success(self, attempt_id: str) -> None:
        """Keep probe validation separate from settlement of its billed request."""
        self.validate_resume()
        self._append(
            {
                "event": "route_probe_passed",
                "attempt_id": attempt_id,
                "plan_digest": self.plan_digest,
                "config_digest": self.config_digest,
            }
        )

    def accept_uncertain_charge(self, attempt_id: str, *, reason: str) -> None:
        """Record operator acceptance of a full reservation, retaining unknown actual cost."""
        self.validate_resume()
        records = self.records()
        reserved = next((r for r in records if r["event"] == "reserved"
                         and r["attempt_id"] == attempt_id), None)
        finished = next((r for r in reversed(records) if r["event"] == "finished"
                         and r["attempt_id"] == attempt_id), None)
        if not reason.strip() or reserved is None or finished is None \
                or finished["cost_usd"] is not None \
                or finished["status"] != "billing_uncertain":
            raise ValueError("only an unknown settled charge can be accepted at its reservation")
        if any(r["event"] == "uncertain_charge_accepted" and r["attempt_id"] == attempt_id
               for r in records):
            return
        self._append({
            "event": "uncertain_charge_accepted", "attempt_id": attempt_id,
            "bound_usd": reserved["bound_usd"], "actual_cost_usd": None, "reason": reason,
            "plan_digest": self.plan_digest, "config_digest": self.config_digest,
        })

    def reconcile(self, gate: SpendGate) -> set[str]:
        """Charge unresolved dispatched reservations at their full bound."""
        self.validate_resume()
        records = self.records()
        finished = {
            record["attempt_id"]: record for record in records if record["event"] == "finished"
        }
        accepted = {
            record["attempt_id"]: record for record in records
            if record["event"] == "uncertain_charge_accepted"
        }
        used: set[str] = set()
        for record in records:
            if record["event"] == "attempt_started":
                used.add(str(record["attempt_id"]))
                continue
            if record["event"] != "reserved":
                continue
            attempt_id = str(record["attempt_id"])
            if attempt_id in used:
                raise AttemptAlreadyUsed(f"duplicate durable attempt identity: {attempt_id}")
            used.add(attempt_id)
            bound = Decimal(record["bound_usd"])
            if finished.get(attempt_id, {}).get("status") == "not_sent":
                continue
            gate.reserve(bound)
            if attempt_id not in finished:
                gate.settle(bound, None)
                self.finish(attempt_id, cost=None, status="billing_uncertain")
            else:
                cost = finished[attempt_id]["cost_usd"]
                if cost is None and attempt_id in accepted:
                    acknowledgement = accepted[attempt_id]
                    if Decimal(acknowledgement["bound_usd"]) != bound \
                            or acknowledgement.get("actual_cost_usd") is not None \
                            or not acknowledgement.get("reason", "").strip():
                        raise ValueError(
                            "uncertain-charge acknowledgement differs from reservation"
                        )
                    # This charges a conservative bound to the spend ledger.
                    # The original finished event continues to say cost_usd=None.
                    cost = str(bound)
                gate.settle(bound, float(cost) if cost is not None else None)
        return used


@dataclass
class RequestBudget:
    """One reservation for every transport request, including retries."""

    gate: SpendGate
    bound: Decimal
    journal: AttemptJournal
    attempt_gate: SpendGate | None = None

    def call(
        self, coordinate: str, request_id: str, dispatch: Callable[[], T],
        *, was_dispatched: Callable[[], bool] | None = None,
    ) -> T:
        if self.attempt_gate is not None:
            self.attempt_gate.reserve(self.bound)
        try:
            self.gate.reserve(self.bound)
        except BaseException:
            if self.attempt_gate is not None:
                self.attempt_gate.release(self.bound)
            raise
        try:
            self.journal.begin(coordinate, request_id, self.bound)
        except BaseException:
            self.gate.release(self.bound)
            if self.attempt_gate is not None:
                self.attempt_gate.release(self.bound)
            raise
        try:
            result = dispatch()
        except BaseException as error:
            if was_dispatched is not None and not was_dispatched():
                self.gate.release(self.bound)
                if self.attempt_gate is not None:
                    self.attempt_gate.release(self.bound)
                self.journal.finish(request_id, cost=Decimal(0), status="not_sent")
                raise
            cost = error.usage.get("cost_usd") if isinstance(error, BilledResponseError) else None
            self.gate.settle(self.bound, cost)
            if self.attempt_gate is not None:
                self.attempt_gate.settle(self.bound, cost)
            self.journal.finish(
                request_id, cost=Decimal(str(cost)) if cost is not None else None,
                status=self.gate.halt or "provider_failure",
            )
            raise
        cost = getattr(result, "cost_usd", None)
        self.gate.settle(self.bound, cost)
        if self.attempt_gate is not None:
            self.attempt_gate.settle(self.bound, cost)
        self.journal.finish(
            request_id,
            cost=Decimal(str(cost)) if cost is not None else None,
            status=self.gate.halt or "settled",
        )
        if self.gate.halt == "billing_uncertain":
            raise ValueError("billing_uncertain")
        return result


@dataclass
class JournaledAgentClient(BudgetedAgentClient):
    """Reuse hosted execution and per-attempt caps, adding the run's durable ledger."""

    run_gate: SpendGate | None = None
    journal: AttemptJournal | None = None
    cell_key: str = ""
    coordinate: str = ""
    _request_number: int = field(default=0, init=False)

    def _openrouter_turn(
        self, messages: list[dict[str, Any]], route: OpenRouterTurnRoute = HAIKU_TURN_ROUTE,
        tools: list[dict[str, Any]] | None = None,
        *, deadline: float | None = None, on_dispatch: Any = None,
    ) -> ModelTurn:
        if self.run_gate is None or self.journal is None or not self.cell_key:
            raise ValueError("hosted extension requests require a run gate and durable identity")
        request_bytes = len(_json_bytes({
            "messages": messages, "tools": self.tools if tools is None else tools,
        }))
        output = self.bounds.max_output_tokens
        if route.max_output_tokens is not None:
            output = min(output, route.max_output_tokens)
        bound = request_cost_bound(route, request_bytes=request_bytes, max_output_tokens=output)
        self._request_number += 1
        sent = False

        def mark_sent() -> None:
            nonlocal sent
            sent = True
            if on_dispatch is not None:
                on_dispatch()

        def dispatch() -> ModelTurn:
            return super(JournaledAgentClient, self)._openrouter_turn(
                messages, route, tools, deadline=deadline, on_dispatch=mark_sent,
            )

        return RequestBudget(self.run_gate, bound, self.journal).call(
            self.coordinate, f"{self.cell_key}:request-{self._request_number}", dispatch,
            was_dispatched=lambda: sent,
        )
