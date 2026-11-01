"""Per-request reservations and durable attempt identities for extension runs."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from verification_pilot.budget import SpendGate

from assay.canonical import canonical_json


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

    def reconcile(self, gate: SpendGate) -> set[str]:
        """Charge unresolved dispatched reservations at their full bound."""
        self.validate_resume()
        records = self.records()
        finished = {
            record["attempt_id"]: record for record in records if record["event"] == "finished"
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
            gate.reserve(bound)
            if attempt_id not in finished:
                gate.settle(bound, None)
                self.finish(attempt_id, cost=None, status="billing_uncertain")
            else:
                cost = finished[attempt_id]["cost_usd"]
                gate.settle(bound, float(cost) if cost is not None else None)
        return used


@dataclass
class RequestBudget:
    """One reservation for every transport request, including retries."""

    gate: SpendGate
    bound: Decimal
    journal: AttemptJournal
    attempt_gate: SpendGate | None = None

    def call(self, coordinate: str, request_id: str, dispatch: Any) -> Any:
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
        except BaseException:
            self.gate.settle(self.bound, None)
            if self.attempt_gate is not None:
                self.attempt_gate.settle(self.bound, None)
            self.journal.finish(request_id, cost=None, status="billing_uncertain")
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
