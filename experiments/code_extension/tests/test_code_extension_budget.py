"""Every transport request gets its own reservation and durable identity."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest
from code_extension.budget import (
    AttemptAlreadyUsed,
    AttemptJournal,
    ConfigurationChanged,
    RequestBudget,
)
from verification_pilot.budget import SpendGate


@dataclass
class Turn:
    cost_usd: float | None


def budget(tmp_path: Path, cap: str = "1") -> tuple[RequestBudget, AttemptJournal]:
    journal = AttemptJournal(
        tmp_path / "attempts.jsonl", "sha256:" + "a" * 64, "sha256:" + "b" * 64
    )
    return RequestBudget(SpendGate(Decimal(cap)), Decimal("0.6"), journal), journal


def test_budget_exhausted_before_second_request(tmp_path: Path) -> None:
    request, journal = budget(tmp_path)
    sent = 0

    def dispatch() -> Turn:
        nonlocal sent
        sent += 1
        return Turn(0.5)

    assert request.call("cell", "request-1", dispatch).cost_usd == 0.5
    with pytest.raises(ValueError, match="budget_exhausted"):
        request.call("cell", "request-2", dispatch)
    assert sent == 1
    assert len([r for r in journal.records() if r["event"] == "reserved"]) == 1


@pytest.mark.parametrize("cost", [None, 0.7])
def test_unknown_or_over_bound_bill_halts(tmp_path: Path, cost: float | None) -> None:
    request, _ = budget(tmp_path, "2")
    with pytest.raises(ValueError, match="billing_uncertain"):
        request.call("cell", "request-1", lambda: Turn(cost))
    assert request.gate.halt == "billing_uncertain"
    assert request.gate.spent_usd == Decimal("0.6" if cost is None else "0.7")
    with pytest.raises(ValueError, match="billing_uncertain"):
        request.call("cell", "request-2", lambda: Turn(0.1))


def test_retry_has_own_identity_and_resume_reconciles(tmp_path: Path) -> None:
    request, journal = budget(tmp_path, "2")
    request.call("cell", "request-1", lambda: Turn(0.2))
    request.call("cell", "request-2", lambda: Turn(0.2))
    assert request.gate.requests == 2
    resumed = SpendGate(Decimal("2"))
    assert journal.reconcile(resumed) == {"request-1", "request-2"}
    assert resumed.spent_usd == Decimal("0.4")
    with pytest.raises(AttemptAlreadyUsed):
        request.call("cell", "request-1", lambda: Turn(0.1))
    changed = AttemptJournal(journal.path, journal.plan_digest, "sha256:" + "c" * 64)
    with pytest.raises(ConfigurationChanged):
        changed.reconcile(SpendGate(Decimal("2")))


def test_reserved_unfinished_attempt_charged_on_resume(tmp_path: Path) -> None:
    _, journal = budget(tmp_path, "2")
    journal.claim_attempt("cell", "attempt-1")
    journal.begin("cell", "request-1", Decimal("0.6"))
    resumed = SpendGate(Decimal("2"))
    assert journal.reconcile(resumed) == {"attempt-1", "request-1"}
    assert resumed.halt == "billing_uncertain"
    assert resumed.spent_usd == Decimal("0.6")
    with pytest.raises(AttemptAlreadyUsed):
        journal.claim_attempt("cell", "attempt-1")


def test_operator_can_charge_unknown_at_reservation_without_inventing_a_bill(
    tmp_path: Path,
) -> None:
    request, journal = budget(tmp_path, "2")
    with pytest.raises(ValueError, match="billing_uncertain"):
        request.call("cell", "request-1", lambda: Turn(None))
    original = journal.records()[-1]
    journal.accept_uncertain_charge("request-1", reason="Operator authorized bounded recovery")
    journal.accept_uncertain_charge("request-1", reason="Operator authorized bounded recovery")
    assert len([r for r in journal.records() if r["event"] == "uncertain_charge_accepted"]) == 1
    assert [r for r in journal.records() if r["event"] == "finished"] == [original]
    assert original["cost_usd"] is None
    gate = SpendGate(Decimal("2"))
    journal.reconcile(gate)
    assert gate.halt is None and gate.spent_usd == Decimal("0.6")
    continued = RequestBudget(gate, Decimal("0.6"), journal)
    continued.call("next-cell", "request-2", lambda: Turn(0.4))
    assert gate.spent_usd == Decimal("1.0")
    with pytest.raises(AttemptAlreadyUsed):
        continued.call("cell", "request-1", lambda: Turn(0.1))


def test_acceptance_cannot_clear_an_over_bound_bill_or_increase_the_cap(tmp_path: Path) -> None:
    request, journal = budget(tmp_path, "2")
    with pytest.raises(ValueError, match="billing_uncertain"):
        request.call("cell", "request-1", lambda: Turn(0.7))
    with pytest.raises(ValueError, match="only an unknown"):
        journal.accept_uncertain_charge("request-1", reason="Operator authorized recovery")
    gate = SpendGate(Decimal("2"))
    journal.reconcile(gate)
    assert gate.halt == "billing_uncertain" and gate.spent_usd == Decimal("0.7")


def test_accepted_unknown_still_consumes_the_spend_cap(tmp_path: Path) -> None:
    request, journal = budget(tmp_path, "2")
    with pytest.raises(ValueError, match="billing_uncertain"):
        request.call("cell", "request-1", lambda: Turn(None))
    journal.accept_uncertain_charge("request-1", reason="Operator authorized recovery")
    gate = SpendGate(Decimal("0.8"))
    journal.reconcile(gate)
    continued = RequestBudget(gate, Decimal("0.6"), journal)
    with pytest.raises(ValueError, match="budget_exhausted"):
        continued.call("next", "request-2", lambda: pytest.fail("cap was bypassed"))
