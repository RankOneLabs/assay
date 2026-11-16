"""Pure, itemized study budget in USD, including one probe per plan."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from code_extension.fact_shapes.settings import PerAttemptCaps, StudyModelName


@dataclass(frozen=True)
class PilotCharge:
    settled_cost: Decimal | None
    reservation: Decimal
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


def measured_mean(model: StudyModelName, charges: tuple[PilotCharge, ...]) -> Decimal | None:
    """Unknown charges use reservations; Argon tokens are repriced at 4/20."""
    if not charges:
        return None
    total = Decimal(0)
    for charge in charges:
        if model == "argon":
            if charge.prompt_tokens is None or charge.completion_tokens is None:
                total += charge.reservation
            else:
                total += (
                    Decimal(charge.prompt_tokens) * 4 + Decimal(charge.completion_tokens) * 20
                ) / 1_000_000
        else:
            total += charge.settled_cost if charge.settled_cost is not None else charge.reservation
    return total / len(charges)


@dataclass(frozen=True)
class ModelPrice:
    model: StudyModelName
    measured: Decimal | None = None


@dataclass(frozen=True)
class Plan:
    model: StudyModelName
    attempts: int


type ComponentName = Literal["main", "pilot", "validation", "library_rerun"]


@dataclass(frozen=True)
class Component:
    name: ComponentName
    plans: tuple[Plan, ...]


DEFAULT_COMPONENTS = (
    Component("main", tuple(Plan(m, 180) for m in ("sol", "argon", "midtier"))),
    Component("pilot", (Plan("sol", 12), Plan("argon", 6), Plan("midtier", 6))),
    Component("validation", tuple(Plan(m, 20) for m in ("sol", "argon", "midtier"))),
    Component("library_rerun", (Plan("midtier", 11),)),
)


@dataclass(frozen=True)
class Item:
    component: ComponentName
    model: StudyModelName
    attempts: int
    unit_price: Decimal
    source: Literal["measured", "cap"]
    attempt_subtotal: Decimal
    probe_count: int
    probe_cost: Decimal


@dataclass(frozen=True)
class Budget:
    items: tuple[Item, ...]
    total: Decimal


@dataclass(frozen=True)
class BudgetError:
    message: str


def budget(
    caps: PerAttemptCaps,
    prices: tuple[ModelPrice, ...] = (),
    components: tuple[Component, ...] = DEFAULT_COMPONENTS,
) -> Budget | BudgetError:
    expected = {"main": 540, "pilot": 24, "validation": 60, "library_rerun": 11}
    if len(components) != 4 or {c.name for c in components} != set(expected):
        return BudgetError("Exactly the four study components are required")
    means = {p.model: p.measured for p in prices}
    if len(means) != len(prices):
        return BudgetError("Duplicate model price")
    items: list[Item] = []
    for component in components:
        if sum(p.attempts for p in component.plans) != expected[component.name] or any(
            p.attempts < 0 for p in component.plans
        ):
            return BudgetError(f"Invalid attempt count for {component.name}")
        if component.name == "library_rerun" and any(p.model != "midtier" for p in component.plans):
            return BudgetError("Library rerun requires midtier")
        for model in sorted({p.model for p in component.plans}):
            plans = tuple(p for p in component.plans if p.model == model)
            cap: Decimal = getattr(caps, model)
            mean = means.get(model)
            price = cap if mean is None else mean
            if not price.is_finite() or price < 0:
                return BudgetError("Invalid measured cost")
            attempts = sum(p.attempts for p in plans)
            items.append(
                Item(
                    component.name,
                    model,
                    attempts,
                    price,
                    "cap" if mean is None else "measured",
                    attempts * price,
                    len(plans),
                    len(plans) * cap,
                )
            )
    return Budget(tuple(items), sum((i.attempt_subtotal + i.probe_cost for i in items), Decimal(0)))
