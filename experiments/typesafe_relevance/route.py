"""``route()``: the round 4 decision over the feature catalogue's probabilities.

Written as in comms/relevance-jev-round-spec.md::

    any excl_* ≥ T_ex                                     → drop
    needs_thread ≥ T_t                                    → review
    answerable_from_post ≥ T_a and about_agent_work ≥ T_w → respond
    points_somewhere ≥ T_p                                → review
    otherwise                                             → drop
    a deciding feature within ±m of its threshold         → review

The first five lines are checked in order and stop at the first match. The margin
overrides them: if any feature the path consulted is within ±m of its threshold,
the post goes to review. The exclusion line consults one value, the largest
``excl_*`` probability, since that alone decides whether "any" holds. Every answer
named ``excl_*`` is an exclusion, so the catalogue decides which ones exist.

``mappings.py`` is not touched: its SHA-256 is pinned in published evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

Action = Literal["respond", "review", "drop"]

EXCLUSION_PREFIX = "excl_"
#: The features ``route()`` reads besides the exclusions.
ROUTED = ("needs_thread", "answerable_from_post", "about_agent_work", "points_somewhere")


@dataclass(frozen=True, slots=True)
class Thresholds:
    """Every threshold starts at 0.5 and the margin at 0.1; nothing is fitted."""

    exclusion: float = 0.5
    thread: float = 0.5
    answerable: float = 0.5
    about: float = 0.5
    points: float = 0.5
    margin: float = 0.1


def _noul(answers: Mapping[str, Any], name: str) -> float:
    value = answers.get(name)
    if not isinstance(value, Mapping) or not isinstance(value.get("noul"), (int, float)):
        raise ValueError(f"missing noul for {name}")
    return float(value["noul"])


DEFAULT = Thresholds()


def route(answers: Mapping[str, Any], t: Thresholds = DEFAULT) -> dict[str, Any]:
    """Decide respond / review / drop from one post's feature probabilities."""
    excl = {
        key.removeprefix(EXCLUSION_PREFIX): _noul(answers, key)
        for key in answers
        if key.startswith(EXCLUSION_PREFIX)
    }
    if not excl:
        raise ValueError("no excl_* answers")
    top = max(excl, key=excl.__getitem__)
    thread = _noul(answers, "needs_thread")
    answerable = _noul(answers, "answerable_from_post")
    about = _noul(answers, "about_agent_work")
    points = _noul(answers, "points_somewhere")

    consulted: list[tuple[str, float, float]] = [(f"excl_{top}", excl[top], t.exclusion)]
    if excl[top] >= t.exclusion:
        action: Action = "drop"
        line = "exclusion"
    else:
        consulted.append(("needs_thread", thread, t.thread))
        if thread >= t.thread:
            action, line = "review", "needs_thread"
        else:
            consulted += [
                ("answerable_from_post", answerable, t.answerable),
                ("about_agent_work", about, t.about),
            ]
            if answerable >= t.answerable and about >= t.about:
                action, line = "respond", "respond"
            else:
                consulted.append(("points_somewhere", points, t.points))
                if points >= t.points:
                    action, line = "review", "points_somewhere"
                else:
                    action, line = "drop", "otherwise"

    close = [name for name, value, threshold in consulted if abs(value - threshold) <= t.margin]
    return {
        "action": "review" if close else action,
        "path_action": action,
        "line": line,
        "margin": close,
        "exclusion": top if excl[top] >= t.exclusion else None,
        "features": {
            **{f"excl_{name}": value for name, value in excl.items()},
            "needs_thread": thread,
            "answerable_from_post": answerable,
            "about_agent_work": about,
            "points_somewhere": points,
        },
    }
