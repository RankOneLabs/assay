"""Descriptive analysis of the fixed fact-shapes study."""

import argparse
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

from verification_pilot.self_trust.wilson import wilson

from code_extension.fact_shapes.attempts import Attempt, Err, read_attempts
from code_extension.fact_shapes.cells import CELLS, Cell, Feature, Shape, TaskType
from code_extension.fact_shapes.mechanism import (
    holder_opened_with_read_file,
    holder_seen,
    miss_type,
)
from code_extension.fact_shapes.outcome import (
    AttemptStatus,
    Held,
    Missed,
    Scored,
    Stopped,
    Unscored,
    score,
)
from code_extension.fact_shapes.reporting import completion_claim, mirrored_state_count

CONTROL_THRESHOLD = 20
ANCHOR_THRESHOLD = 20
INTERVAL_LABEL = (
    "Wilson 95% intervals describe execution variability on 3 fixed features, "
    "not sampling error over tasks."
)


@dataclass(frozen=True)
class Row:
    model: str
    cell: Cell
    status: AttemptStatus
    holder_seen: bool = False
    mirrored_state_count: int = 0
    miss_type: str | None = None
    holder_opened: bool = False
    completion_claim: bool = False


@dataclass(frozen=True)
class Count:
    missed: int = 0
    scored: int = 0

    @property
    def interval(self) -> str:
        return wilson(self.missed, self.scored) if self.scored else "unavailable"

    def __str__(self) -> str:
        return f"{self.missed} of {self.scored} ({self.interval})"


def count(rows: Iterable[Row], *, anchor: bool = False, seen: bool = False) -> Count:
    x = n = 0
    for row in rows:
        if not isinstance(row.status, Scored):
            continue
        fact = row.status.facts.get(row.cell.anchor_fact_id if anchor else row.cell.fact_id)
        if seen:
            if isinstance(fact, Missed):
                n += 1
                x += row.holder_seen
        elif isinstance(fact, (Missed, Held)):
            n += 1
            x += isinstance(fact, Missed)
    return Count(x, n)


@dataclass(frozen=True)
class Exclusion:
    model: str
    control: Count
    anchor: Count

    @property
    def excluded(self) -> bool:
        return (
            100 * self.control.missed > CONTROL_THRESHOLD * self.control.scored
            or 100 * self.anchor.missed > ANCHOR_THRESHOLD * self.anchor.scored
        )


def exclusions(rows: tuple[Row, ...]) -> tuple[Exclusion, ...]:
    def part(selected: tuple[Row, ...], *, anchor: bool = False) -> Count:
        return Count(
            count(selected, anchor=anchor).missed,
            sum(isinstance(r.status, Scored) for r in selected),
        )

    return tuple(
        Exclusion(
            model,
            part(tuple(r for r in rows if r.model == model and r.cell.shape == "type_enforced")),
            part(tuple(r for r in rows if r.model == model), anchor=True),
        )
        for model in sorted({r.model for r in rows})
    )


def miss_counts(
    rows: tuple[Row, ...], *, anchor: bool = False
) -> dict[tuple[str, str, str, str], Count]:
    return {
        (model, shape, task, feature): count(
            (
                r
                for r in rows
                if r.model == model
                and r.cell.shape == shape
                and r.cell.task_type == task
                and (feature == "pooled" or r.cell.feature == feature)
            ),
            anchor=anchor,
        )
        for model in sorted({r.model for r in rows})
        for shape in get_args(Shape)
        for task in get_args(TaskType)
        for feature in (*get_args(Feature), "pooled")
    }


def unscored_table(rows: tuple[Row, ...]) -> Counter[tuple[str, str]]:
    return Counter((r.model, r.status.reason) for r in rows if isinstance(r.status, Unscored))


def stop_table(rows: tuple[Row, ...]) -> Counter[tuple[str, str]]:
    return Counter((r.model, r.status.stop_kind) for r in rows if isinstance(r.status, Stopped))


def table(headers: tuple[str, ...], rows: Iterable[tuple[object, ...]]) -> str:
    def line(values: Iterable[object]) -> str:
        return (
            "| " + " | ".join(str(v).replace("|", "\\|").replace("\n", " ") for v in values) + " |"
        )

    return "\n".join((line(headers), line("---" for _ in headers), *(line(r) for r in rows)))


def planned_comparisons(rows: tuple[Row, ...]) -> str:
    excluded = {e.model for e in exclusions(rows) if e.excluded}
    kept = tuple(r for r in rows if r.model not in excluded)
    headings = (
        "Each shape against type_enforced",
        "Sibling and outside against reference",
        "Rename against additive",
        "Holder seen among misses",
    )
    sections = []
    for number, heading in enumerate(headings, 1):
        results: list[tuple[object, ...]] = []
        pairs = (
            [(s, "type_enforced") for s in get_args(Shape) if s != "type_enforced"]
            if number == 1
            else [(s, "reference") for s in ("sibling_only", "outside_code")]
            if number == 2
            else [(s, s) for s in ("name_only", "sibling_only", "outside_code")]
            if number == 3
            else [(s, "name_only") for s in ("sibling_only", "outside_code")]
        )
        for model in sorted({r.model for r in kept}):
            for task in ("rename vs additive",) if number == 3 else get_args(TaskType):
                for feature in (*get_args(Feature), "pooled"):
                    subset = tuple(
                        r
                        for r in kept
                        if r.model == model and (feature == "pooled" or r.cell.feature == feature)
                    )
                    for left, right in pairs:
                        a = count(
                            (
                                r
                                for r in subset
                                if r.cell.shape == left
                                and r.cell.task_type == ("rename" if number == 3 else task)
                            ),
                            seen=number == 4,
                        )
                        b = count(
                            (
                                r
                                for r in subset
                                if r.cell.shape == right
                                and r.cell.task_type == ("additive" if number == 3 else task)
                            ),
                            seen=number == 4,
                        )
                        results.append((model, task, feature, left, a, right, b))
        sections.append(
            f"### {number}. {heading}\n\n"
            + table(
                ("Model", "Task", "Feature", "Side A", "x of n (95%)", "Side B", "x of n (95%)"),
                results,
            )
        )
    return "\n\n".join(sections)


def import_distance_counts(rows: tuple[Row, ...]) -> dict[tuple[str, str, str, int], Count]:
    keys = sorted(
        {
            (r.model, r.cell.task_type, r.cell.feature, r.cell.import_hops)
            for r in rows
            if r.cell.import_hops is not None
        }
    )
    return {
        key: count(
            r
            for r in rows
            if (r.model, r.cell.task_type, r.cell.feature, r.cell.import_hops) == key
        )
        for key in keys
    }


def h5_counts(rows: tuple[Row, ...]) -> dict[str, tuple[int, int]]:
    """Mirrored declarations and attempts, restricted to scored additive work."""
    selected = tuple(
        r
        for r in rows
        if r.cell.shape == "existing_state"
        and r.cell.task_type == "additive"
        and isinstance(r.status, Scored)
    )
    return {
        model: (
            sum(r.mirrored_state_count for r in selected if r.model == model),
            sum(r.model == model for r in selected),
        )
        for model in sorted({r.model for r in rows})
    }


def reader_update_counts(rows: tuple[Row, ...]) -> dict[tuple[str, str], Count]:
    """Aggregate rename facts per model and fixed feature across repeats."""
    return {
        (model, feature): count(
            r
            for r in rows
            if r.model == model
            and r.cell.feature == feature
            and r.cell.shape == "existing_state"
            and r.cell.task_type == "rename"
        )
        for model in sorted({r.model for r in rows})
        for feature in get_args(Feature)
    }


def render_report(rows: tuple[Row, ...]) -> str:
    sections = ["# Fact shapes", INTERVAL_LABEL]
    for title, anchor in (("Miss counts", False), ("Anchor fact counts", True)):
        sections.append(
            f"## {title}\n\n"
            + table(
                ("Model", "Shape", "Task", "Feature", "x of n (95%)"),
                ((*key, value) for key, value in miss_counts(rows, anchor=anchor).items()),
            )
        )
    sections.append("## Planned comparisons\n\n" + planned_comparisons(rows))
    sections.append(
        "## Excluded models\n\n"
        + table(
            ("Model", "Control", "Anchor", "Excluded"),
            (
                (
                    e.model,
                    str(e.control) if e.control.scored else "not evaluable",
                    str(e.anchor) if e.anchor.scored else "not evaluable",
                    e.excluded,
                )
                for e in exclusions(rows)
            ),
        )
    )
    for title, counts in (
        ("Unscored attempts by reason", unscored_table(rows)),
        ("Limit stops by kind", stop_table(rows)),
    ):
        sections.append(
            f"## {title}\n\n"
            + table(
                ("Model", "Reason/kind", "Attempts"),
                ((*key, n) for key, n in sorted(counts.items())),
            )
        )
    sections.append(
        "## Import-distance falsifier\n\n"
        + table(
            ("Model", "Task", "Feature", "Import hops", "x of n (95%)"),
            ((*key, value) for key, value in import_distance_counts(rows).items()),
        )
    )
    sections.append(
        "## H5 duplicate count\n\n"
        "Mirrored-state count (lower bound), over scored additive attempts only.\n\n"
        + table(
            (
                "Model",
                "Mirrored declarations",
                "Scored additive attempts",
                "Existing-state additive result",
            ),
            (
                (
                    model,
                    *values,
                    count(
                        r
                        for r in rows
                        if r.model == model
                        and r.cell.shape == "existing_state"
                        and r.cell.task_type == "additive"
                    ),
                )
                for model, values in h5_counts(rows).items()
            ),
        )
        + "\n\n"
        + table(
            ("Model", "Feature", "Fact", "x of n (95%)"),
            ((*key, "reader-update", value) for key, value in reader_update_counts(rows).items()),
        )
    )
    sections.append(
        "## Exploratory\n\n"
        + table(
            ("Model", "Miss type", "Holder opened with read_file", "Completion claims", "Attempts"),
            (
                (*key, n)
                for key, n in sorted(
                    Counter(
                        (r.model, r.miss_type or "none", r.holder_opened, r.completion_claim)
                        for r in rows
                    ).items()
                )
            ),
        )
    )
    return "\n\n".join(sections) + "\n"


def from_attempt(
    model: str,
    cell: Cell,
    attempt: Attempt,
    status: AttemptStatus,
    state_fields: tuple[str, ...] = (),
) -> Row:
    if cell.shape == "existing_state" and cell.task_type == "additive" and not state_fields:
        raise ValueError("H5 additive analysis requires a nonempty state_fields inventory")
    fact = next((f for f in attempt.variant.facts if f.id == cell.fact_id), None)
    claim = completion_claim(status, attempt.self_assessed_verdict)
    outcome = status.facts.get(cell.fact_id) if isinstance(status, Scored) else None
    return Row(
        model,
        cell,
        status,
        holder_seen(attempt, fact.holder) if fact else False,
        mirrored_state_count(attempt.patch, state_fields),
        miss_type(attempt, fact.holder, outcome) if fact and outcome else None,
        holder_opened_with_read_file(attempt, fact.holder) if fact else False,
        claim.completion_claim if claim else False,
    )


def main() -> None:
    """Load explicit retained variant metadata alongside frozen cohort plans.

    Each plan's `variants` maps archive cell IDs to serialized Attempt Variant
    dataclasses; `state_fields` supplies the reviewed state inventory names.
    Optional `replay_outputs` maps archive cell IDs to pinned typecheck output.
    Missing replay evidence is reported as unscored by the outcome transform.
    """
    import json

    from pydantic import TypeAdapter

    from code_extension.fact_shapes.attempts import Variant
    from code_extension.launch import FrozenCohort

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--cohort", type=Path, required=True)
    args = parser.parse_args()
    raw = json.loads(args.cohort.read_text())
    # FrozenCohort intentionally forbids analysis-only metadata.
    frozen = {
        **raw,
        "plans": [
            {
                k: v
                for k, v in p.items()
                if k not in {"variants", "state_fields", "model", "replay_outputs"}
            }
            for p in raw["plans"]
        ],
    }
    cohort = FrozenCohort.model_validate(frozen)
    rows: list[Row] = []
    for plan, metadata in zip(cohort.plans, raw["plans"], strict=True):
        if "variants" not in metadata:
            parser.exit(1, "Cohort plans require retained variants metadata for fact scoring.\n")
        variants = TypeAdapter(dict[str, Variant]).validate_python(metadata["variants"])
        result = read_attempts(args.store, plan.plan_digest, variants)
        if isinstance(result, Err):
            parser.exit(1, f"{result.error}\n")
        for attempt in result.value:
            cell = next(c for c in CELLS if any(f.id == c.fact_id for f in attempt.variant.facts))
            state_fields = TypeAdapter(tuple[str, ...]).validate_python(
                metadata.get("state_fields", ())
            )
            if cell.shape == "existing_state" and cell.task_type == "additive" and not state_fields:
                parser.exit(1, "H5 additive analysis requires a nonempty state_fields inventory.\n")
            rows.append(
                from_attempt(
                    metadata.get("model", plan.name),
                    cell,
                    attempt,
                    score(attempt, metadata.get("replay_outputs", {}).get(attempt.cell)),
                    state_fields,
                )
            )
    print(render_report(tuple(rows)), end="")


if __name__ == "__main__":
    main()
