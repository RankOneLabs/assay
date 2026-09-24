"""Score round 4's arms against the blind v4 labels.

Measures, as in comms/relevance-jev-round-spec.md:

- exclusion: excluded or not, and category
- substance, where both sides say not excluded
- final action (respond / review / drop); production, which has no review state,
  on surfaced vs. dropped only, with respond and review both counting as surfaced
- complete decision: same exclusion category and, when neither excludes, same
  substance

Posts flagged "need the thread" are counted and left out. Repeated post text is
scored once, on its first case.

An arm's substance reads the same features ``route()`` does: ``in_post`` when
``answerable_from_post`` and ``about_agent_work`` both clear their thresholds,
``pointer`` when ``points_somewhere`` does, otherwise ``none``.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from typesafe_relevance.route import DEFAULT, Thresholds

HUMAN_ACTION = {"in_post": "respond", "pointer": "review", "none": "drop"}


def human_decision(label: Mapping[str, Any]) -> dict[str, Any]:
    exclusion = label["exclusion"]
    substance = label.get("substance") if exclusion == "none" else None
    return {
        "exclusion": None if exclusion == "none" else exclusion,
        "substance": substance,
        "action": "drop" if exclusion != "none" else HUMAN_ACTION[str(substance)],
    }


def arm_decision(route: Mapping[str, Any], t: Thresholds = DEFAULT) -> dict[str, Any]:
    f = route["features"]
    if f["answerable_from_post"] >= t.answerable and f["about_agent_work"] >= t.about:
        substance = "in_post"
    elif f["points_somewhere"] >= t.points:
        substance = "pointer"
    else:
        substance = "none"
    return {
        "exclusion": route["exclusion"],
        "substance": None if route["exclusion"] else substance,
        "action": route["action"],
    }


def _rate(pairs: Sequence[tuple[Any, Any]]) -> dict[str, Any]:
    agree = sum(a == b for a, b in pairs)
    return {"agree": agree, "n": len(pairs), "rate": agree / len(pairs) if pairs else None}


def score(
    human: Mapping[int, dict[str, Any]], arm: Mapping[int, dict[str, Any]]
) -> dict[str, Any]:
    ids = sorted(human)
    both_in = [e for e in ids if human[e]["exclusion"] is None and arm[e]["exclusion"] is None]
    return {
        "excluded_or_not": _rate(
            [(human[e]["exclusion"] is None, arm[e]["exclusion"] is None) for e in ids]
        ),
        "exclusion_category": _rate([(human[e]["exclusion"], arm[e]["exclusion"]) for e in ids]),
        "substance_both_not_excluded": _rate(
            [(human[e]["substance"], arm[e]["substance"]) for e in both_in]
        ),
        "final_action": _rate([(human[e]["action"], arm[e]["action"]) for e in ids]),
        "surfaced_or_dropped": _rate(
            [(human[e]["action"] != "drop", arm[e]["action"] != "drop") for e in ids]
        ),
        "complete_decision": _rate(
            [
                (
                    (human[e]["exclusion"], human[e]["substance"]),
                    (arm[e]["exclusion"], arm[e]["substance"]),
                )
                for e in ids
            ]
        ),
        "action_confusion": {
            f"{h}->{a}": n
            for (h, a), n in sorted(
                Counter((human[e]["action"], arm[e]["action"]) for e in ids).items()
            )
        },
    }


def run(args: argparse.Namespace) -> None:
    key = json.loads(args.key.read_text(encoding="utf-8"))["cases"]
    packet = json.loads(args.packet.read_text(encoding="utf-8"))["cases"]
    labels = json.loads(args.labels.read_text(encoding="utf-8"))["cases"]
    arms: dict[str, Any] = {}
    for path in args.arms:
        arms.update(json.loads(path.read_text(encoding="utf-8"))["cells"])
    eid_of = {c["case_id"]: int(c["evaluation_id"]) for c in key}
    production = {int(c["evaluation_id"]): bool(c["production_decision"]) for c in key}

    first_of_text: dict[tuple[Any, Any], int] = {}
    for case in sorted(packet, key=lambda c: c["case_id"]):
        first_of_text.setdefault((case["text"], case.get("parent_text")), case["case_id"])
    kept = set(first_of_text.values())

    flagged = [c for c in labels if c.get("needs_thread")]
    scored = [c for c in labels if c["case_id"] in kept and not c.get("needs_thread")]
    human = {eid_of[c["case_id"]]: human_decision(c) for c in scored}

    results: dict[str, Any] = {
        "cases": len(labels),
        "repeated_text_dropped": len(labels) - len(kept),
        "needs_thread_flagged": len(flagged),
        "scored": len(human),
        "human_actions": dict(Counter(h["action"] for h in human.values())),
        "arms": {
            "production": {
                "surfaced_or_dropped": _rate(
                    [(human[e]["action"] != "drop", production[e]) for e in sorted(human)]
                )
            }
        },
    }
    for arm_id in sorted({cell["arm"] for cell in arms.values()}):
        missing = [e for e in human if f"{arm_id}:{e}" not in arms]
        if missing:
            results["arms"][arm_id] = {"missing_cells": len(missing)}
            continue
        decisions = {e: arm_decision(arms[f"{arm_id}:{e}"]["route"]) for e in human}
        results["arms"][arm_id] = score(human, decisions)

    args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--arms", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
