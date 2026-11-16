from dataclasses import replace
from decimal import Decimal

from code_extension.fact_shapes.budget import (
    DEFAULT_COMPONENTS,
    Budget,
    BudgetError,
    Component,
    ModelPrice,
    PilotCharge,
    Plan,
    budget,
    measured_mean,
)
from code_extension.fact_shapes.settings import PerAttemptCaps

CAPS = PerAttemptCaps(sol=Decimal(1), argon=Decimal(2), midtier=Decimal(3))


def test_cap_budget():
    result = budget(CAPS)
    assert isinstance(result, Budget)
    assert result.total == Decimal(180 * 6 + 12 + 6 * 2 + 6 * 3 + 20 * 6 + 33 + 3 * 6 + 3)
    assert {c.name: sum(p.attempts for p in c.plans) for c in DEFAULT_COMPONENTS} == {
        "main": 540,
        "pilot": 24,
        "validation": 60,
        "library_rerun": 11,
    }
    assert all(i.model == "midtier" for i in result.items if i.component == "library_rerun")


def test_measured_prices_and_probes():
    result = budget(CAPS, (ModelPrice("sol", Decimal(".25")),))
    assert isinstance(result, Budget)
    for item in result.items:
        if item.model == "sol":
            assert item.source == "measured"
            assert item.unit_price == Decimal(".25")
            assert item.probe_cost == item.probe_count * CAPS.sol


def test_repricing_and_unknowns():
    assert measured_mean("argon", (PilotCharge(Decimal(3), Decimal(9), 1_000_000, 100_000),)) == 6
    assert measured_mean("argon", (PilotCharge(Decimal(3), Decimal(9)),)) == 9
    assert (
        measured_mean("sol", (PilotCharge(None, Decimal(9)), PilotCharge(Decimal(1), Decimal(9))))
        == 5
    )
    assert measured_mean("sol", ()) is None


def test_invalid_components():
    bad = replace(DEFAULT_COMPONENTS[0], plans=(Plan("sol", 539),))
    assert isinstance(budget(CAPS, components=(bad, *DEFAULT_COMPONENTS[1:])), BudgetError)
    bad_library = Component("library_rerun", (Plan("sol", 11),))
    assert isinstance(budget(CAPS, components=(*DEFAULT_COMPONENTS[:3], bad_library)), BudgetError)
