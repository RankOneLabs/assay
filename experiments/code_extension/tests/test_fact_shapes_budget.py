from dataclasses import replace
from decimal import Decimal

from code_extension.fact_shapes.budget import (
    DEFAULT_COMPONENTS,
    Component,
    Err,
    ModelPrice,
    Ok,
    PilotCharge,
    Plan,
    budget,
    measured_mean,
)
from code_extension.fact_shapes.settings import PerAttemptCaps

CAPS = PerAttemptCaps(sol=Decimal(1), argon=Decimal(2), midtier=Decimal(3))


def test_cap_budget():
    result = budget(CAPS)
    assert isinstance(result, Ok)
    result = result.value
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
    assert isinstance(result, Ok)
    result = result.value
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
    assert isinstance(budget(CAPS, components=(bad, *DEFAULT_COMPONENTS[1:])), Err)
    bad_library = Component("library_rerun", (Plan("sol", 11),))
    assert isinstance(budget(CAPS, components=(*DEFAULT_COMPONENTS[:3], bad_library)), Err)


def test_model_allocations_and_error_context():
    for index, plans in (
        (0, (Plan("sol", 179), Plan("argon", 181), Plan("midtier", 180))),
        (1, (Plan("sol", 6), Plan("argon", 12), Plan("midtier", 6))),
        (2, (Plan("sol", 19), Plan("argon", 21), Plan("midtier", 20))),
    ):
        components = list(DEFAULT_COMPONENTS)
        components[index] = replace(components[index], plans=plans)
        result = budget(CAPS, components=tuple(components))
        assert isinstance(result, Err)
        assert result.error.component == components[index].name
        assert result.error.model in {"sol", "argon"}
    result = budget(CAPS, (ModelPrice("sol", Decimal("-1")),))
    assert isinstance(result, Err)
    assert result.error.component == "main" and result.error.model == "sol"


def test_multiple_plans_add_probes():
    main = replace(
        DEFAULT_COMPONENTS[0],
        plans=(Plan("sol", 90), Plan("sol", 90), Plan("argon", 180), Plan("midtier", 180)),
    )
    result = budget(CAPS, components=(main, *DEFAULT_COMPONENTS[1:]))
    assert isinstance(result, Ok)
    item = next(i for i in result.value.items if i.component == "main" and i.model == "sol")
    assert item.attempts == 180 and item.probe_count == 2 and item.probe_cost == 2
