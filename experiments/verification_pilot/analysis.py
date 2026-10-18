"""Pure, pre-registered inference over the pilot's per-turn measure set."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from statistics import fmean
from typing import Any

from assay.report_engine import exact_sign_test
from verification_pilot.observations import Measured, TurnMeasure

ARMS = ("t1-native", "t1-quoted")
H1_SUBJECTS = 16
H4_PAIRS = 4
H4_P_FLOOR = 0.125


@dataclass(frozen=True, slots=True)
class MeasureCell:
    model: str
    subject: str
    migration: str
    group: str | None
    arm: str
    measures: tuple[TurnMeasure, ...]


def value(cell: MeasureCell, name: str, turn: str = "T1") -> object | None:
    """Return one measured value; absent and unstarted turns remain missing."""
    matches = [item.result for item in cell.measures
               if item.turn == turn and item.name == name]
    if len(matches) > 1:
        raise ValueError(f"duplicate {turn} {name} measure for {cell.subject}/{cell.arm}")
    return matches[0].value if matches and isinstance(matches[0], Measured) else None


def _number(item: object | None) -> float | None:
    if isinstance(item, bool):
        return None
    if isinstance(item, (int, float)):
        return float(item)
    return None


def h1_sign_test(cells: Iterable[MeasureCell], arm: str) -> dict[str, Any]:
    """Two-sided sign test of T1 ownership gap over the 16 base subjects."""
    selected = [cell for cell in cells if cell.arm == arm]
    if len({cell.subject for cell in selected}) != len(selected):
        raise ValueError("duplicate H1 subject/arm")
    gaps = [_number(value(cell, "ownership_gap")) for cell in selected]
    observed = [gap for gap in gaps if gap is not None]
    improved = sum(gap > 0 for gap in observed)
    regressed = sum(gap < 0 for gap in observed)
    return {"arm": arm, "n": len(observed), "planned_n": H1_SUBJECTS,
            "improved": improved, "regressed": regressed,
            "ties": len(observed) - improved - regressed,
            "mean_gap": fmean(observed) if observed else None,
            "p_value": (exact_sign_test(improved, regressed)
                        if len(observed) == H1_SUBJECTS else None),
            "status": "complete" if len(observed) == H1_SUBJECTS else "in_progress"}


def h2_paired_sign_test(cells: Iterable[MeasureCell]) -> dict[str, Any]:
    """Compare quoted minus native T1 ownership gap within each subject."""
    by_subject: dict[str, dict[str, float]] = defaultdict(dict)
    for cell in cells:
        if cell.arm not in ARMS:
            continue
        gap = _number(value(cell, "ownership_gap"))
        if gap is not None:
            if cell.arm in by_subject[cell.subject]:
                raise ValueError("duplicate H2 subject/arm")
            by_subject[cell.subject][cell.arm] = gap
    differences = [arms[ARMS[1]] - arms[ARMS[0]] for arms in by_subject.values()
                   if all(arm in arms for arm in ARMS)]
    improved = sum(diff > 0 for diff in differences)
    regressed = sum(diff < 0 for diff in differences)
    return {"n": len(differences), "improved": improved, "regressed": regressed,
            "ties": len(differences) - improved - regressed,
            "mean_difference": fmean(differences) if differences else None,
            "p_value": exact_sign_test(improved, regressed) if differences else None}


def h4_rename_pairs(cells: Iterable[MeasureCell], arm: str, own_group: str) -> dict[str, Any]:
    """Four rename-matched own versus teammate remnant-inspection contrasts."""
    buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    for cell in cells:
        if cell.arm != arm or cell.group is None:
            continue
        inspected = value(cell, "remnant_path_inspected")
        if isinstance(inspected, bool):
            buckets[cell.migration, cell.group].append(float(inspected))
    pairs: list[dict[str, Any]] = []
    for migration in sorted({key[0] for key in buckets}):
        own = buckets.get((migration, own_group), [])
        teammate = [v for (name, group), values in buckets.items()
                    if name == migration and group != own_group for v in values]
        if own and teammate:
            pairs.append({"migration": migration, "own": fmean(own),
                          "teammate": fmean(teammate),
                          "difference": fmean(own) - fmean(teammate)})
    if len(pairs) > H4_PAIRS:
        raise ValueError("H4 has more than four rename-matched pairs")
    differences = [pair["difference"] for pair in pairs]
    improved = sum(diff > 0 for diff in differences)
    regressed = sum(diff < 0 for diff in differences)
    raw_p = (exact_sign_test(improved, regressed)
             if len(pairs) == H4_PAIRS else None)
    return {"arm": arm, "n": len(pairs), "planned_n": H4_PAIRS, "pairs": pairs,
            "improved": improved, "regressed": regressed,
            "ties": len(pairs) - improved - regressed,
            "mean_difference": fmean(differences) if differences else None,
            "p_value": max(raw_p, H4_P_FLOOR) if raw_p is not None else None,
            "p_floor": H4_P_FLOOR, "decision": "descriptive_only"}


def wide_search_ceiling(cells: Iterable[MeasureCell], arm: str) -> dict[str, Any]:
    """A route crosses the ceiling only when its measured share is strictly >50%."""
    measured = [value(cell, "first_inspection_is_wide_search") for cell in cells
                if cell.arm == arm]
    known = [item for item in measured if isinstance(item, bool)]
    wide = sum(known)
    share = wide / len(known) if known else None
    return {"arm": arm, "repository_wide_first": wide, "n": len(known),
            "share": share, "exceeds_half": share > 0.5 if share is not None else None}


def result_tables(cells: Iterable[MeasureCell]) -> dict[str, Any]:
    """Stable tables consumed by the two generated study pages."""
    rows = tuple(cells)
    models = sorted({cell.model for cell in rows})
    measures: Counter[tuple[str, str, str, str, str]] = Counter()
    for cell in rows:
        for item in cell.measures:
            label = str(item.result.value) if isinstance(item.result, Measured) else "absent"
            measures[cell.model, cell.arm, item.turn, item.name, label] += 1
    return {
        "routes": [{"model": model,
                    "H1": {arm: h1_sign_test((r for r in rows if r.model == model), arm)
                           for arm in ARMS},
                    "H2": h2_paired_sign_test(r for r in rows if r.model == model),
                    "H4": {arm: h4_rename_pairs((r for r in rows if r.model == model),
                                                 arm, "group_a") for arm in ARMS},
                    "ceiling": {arm: wide_search_ceiling(
                        (r for r in rows if r.model == model), arm) for arm in ARMS}}
                   for model in models],
        "measures": [{"model": model, "arm": arm, "turn": turn, "measure": name,
                      "value": label, "count": count}
                     for (model, arm, turn, name, label), count in sorted(measures.items())],
    }
