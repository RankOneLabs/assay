"""Round 4 prompt iteration: run feature variants through JEV and score them.

A variant catalogue holds several wordings of the features that failed, each its
own question, so one JEV call per post answers them all. Scoring reads the blind
labels and reports, per variant, how well it separates the label groups it is
meant to separate (AUC, so no threshold is involved), and then the final action
``route()`` reaches when the variant replaces the v4 feature. Every feature a
variant does not replace comes from the ``jev:v4`` cells in ``arms.json``.

Only the 90 scored posts are run: repeated text is dropped as in scoring.
"""

from __future__ import annotations

import argparse
import itertools
import json
import time
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from typesafe_relevance.backends import BackendError, TypesafeBackend
from typesafe_relevance.catalogue import check_dispatchable, load_catalogue
from typesafe_relevance.route import route
from typesafe_relevance.run_arms import PROJECTS
from typesafe_relevance.run_round4 import read_cases
from typesafe_relevance.score_round4 import HUMAN_ACTION
from typesafe_relevance.state import build_state


def scored_cases(round_dir: Path) -> list[dict[str, Any]]:
    """The 90 scored posts: first copy of each text, with the human label joined on."""
    packet = json.loads((round_dir / "packet/packet.json").read_text(encoding="utf-8"))["cases"]
    labels = {
        c["case_id"]: c
        for c in json.loads((round_dir / "packet/labels.json").read_text(encoding="utf-8"))["cases"]
    }
    key = {
        c["case_id"]: c
        for c in json.loads(
            (round_dir / "packet/answer-key-private.json").read_text(encoding="utf-8")
        )["cases"]
    }
    first: dict[tuple[Any, Any], int] = {}
    for case in sorted(packet, key=lambda c: c["case_id"]):
        first.setdefault((case["text"], case.get("parent_text")), case["case_id"])
    records = {
        int(r["evaluation_id"]): r
        for r in read_cases(
            round_dir / "packet/answer-key-private.json",
            {k: round_dir / f"population/{k}.jsonl" for k in PROJECTS},
        )
    }
    out = []
    for case_id in sorted(first.values()):
        label = labels[case_id]
        if label.get("needs_thread"):
            continue
        group = label["exclusion"] if label["exclusion"] != "none" else f"sub:{label['substance']}"
        action = "drop" if label["exclusion"] != "none" else HUMAN_ACTION[label["substance"]]
        eid = int(key[case_id]["evaluation_id"])
        out.append({"record": records[eid], "evaluation_id": eid, "group": group, "human": action})
    return out


def run(args: argparse.Namespace) -> None:
    catalogue = load_catalogue(args.catalogue)
    check_dispatchable(catalogue.questions)
    cases = scored_cases(args.round)
    output: Path = args.output
    cells: dict[str, Any] = (
        json.loads(output.read_text(encoding="utf-8"))["cells"] if output.exists() else {}
    )
    pending = [c for c in cases if str(c["evaluation_id"]) not in cells]
    print(f"{catalogue.id} {catalogue.version[:12]}: {len(cases)} posts, {len(pending)} to run")
    backend = TypesafeBackend(arm=catalogue.id)
    backend.check_ready()
    if args.dry_run:
        return
    failures = []
    for index, case in enumerate(pending, start=1):
        eid = case["evaluation_id"]
        state = build_state(case["record"], PROJECTS[case["record"]["_project_key"]])
        try:
            answer = backend(state, catalogue.questions, eid)
        except BackendError as error:
            failures.append({"evaluation_id": eid, "detail": error.detail})
            print(f"  FAIL {eid}: {error.detail}")
            continue
        cells[str(eid)] = {"request_id": answer.request_id, "answers": answer.answers}
        output.write_text(
            json.dumps(
                {"catalogue": catalogue.id, "version": catalogue.version, "cells": cells},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        if index % 10 == 0:
            print(f"  [{index}/{len(pending)}]")
        time.sleep(0.2)
    print(f"done, {len(failures)} failures -> {output}")


def auc(positives: Sequence[float], negatives: Sequence[float]) -> float | None:
    """Chance a random positive scores above a random negative; ties count half."""
    if not positives or not negatives:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in positives for n in negatives)
    return wins / (len(positives) * len(negatives))


#: Which label groups each feature family should separate: (positives, negatives).
TARGETS: dict[str, tuple[set[str], set[str]]] = {
    "excl": ({"hype", "sub:none"}, {"sub:in_post", "sub:pointer"}),
    "about": ({"sub:in_post", "sub:pointer"}, {"hype", "sub:none"}),
    "answerable": ({"sub:in_post"}, {"hype", "sub:none", "sub:pointer"}),
    "practitioner": ({"sub:in_post"}, {"hype", "sub:none", "sub:pointer"}),
    "points": ({"sub:pointer"}, {"hype", "sub:none"}),
}

_PREFIXES = {
    "excl_": "excl",
    "about_": "about",
    "answerable_": "answerable",
    "practitioner": "practitioner",
    "points_": "points",
    "worth_opening": "points",
}


def _family(question: str) -> str:
    return next(family for prefix, family in _PREFIXES.items() if question.startswith(prefix))


def _p(answers: Mapping[str, Any], name: str) -> float:
    return float(answers[name]["noul"])


def compose(
    base: Mapping[str, Any],
    variant: Mapping[str, Any],
    *,
    hype: str | None,
    extra_excl: Iterable[str],
    answerable: str | None,
    about: str | None,
    points: str | None = None,
) -> dict[str, Any]:
    """v4 answers with the chosen variants swapped in, in the shape ``route()`` reads."""
    answers = dict(base)
    hype_p = _p(variant, hype) if hype else _p(base, "excl_hype")
    answers["excl_hype"] = {"noul": max([hype_p, *[_p(variant, e) for e in extra_excl]])}
    if answerable:
        answers["answerable_from_post"] = variant[answerable]
    if about:
        answers["about_agent_work"] = variant[about]
    if points:
        answers["points_somewhere"] = variant[points]
    return answers


def score(args: argparse.Namespace) -> None:
    cases = scored_cases(args.round)
    arms = json.loads((args.arms or args.round / "arms.json").read_text(encoding="utf-8"))["cells"]
    variants: dict[str, dict[str, Any]] = {}
    for path in args.variants:
        for k, v in json.loads(path.read_text(encoding="utf-8"))["cells"].items():
            variants.setdefault(k, {}).update(v["answers"])
    base = {
        str(c["evaluation_id"]): arms[f"{args.base}:{c['evaluation_id']}"]["answers"]
        for c in cases
    }
    cases = [c for c in cases if str(c["evaluation_id"]) in variants]
    questions = sorted(set.intersection(*(set(variants[str(c["evaluation_id"])]) for c in cases)))
    if args.only:
        questions = [q for q in questions if q in args.only]

    print(f"{len(cases)} posts\n\nseparation (AUC; 0.5 is chance, 1.0 perfect):")
    for q in questions:
        pos, neg = TARGETS[_family(q)]
        values: dict[str, list[float]] = {}
        for c in cases:
            values.setdefault(c["group"], []).append(_p(variants[str(c["evaluation_id"])], q))
        a = auc(
            [v for g in pos for v in values.get(g, [])],
            [v for g in neg for v in values.get(g, [])],
        )
        print(f"  {q:34} {'n/a' if a is None else f'{a:.2f}'}")

    def of(family: str) -> list[str]:
        return [q for q in questions if _family(q) == family]

    hypes = [None, *[q for q in of("excl") if q.startswith("excl_hype")]]
    extras = [(), *[(q,) for q in of("excl") if not q.startswith("excl_hype")]]
    gates: list[tuple[str | None, str | None]] = [(None, None)]
    gates += [(a, w) for a in [None, *of("answerable")] for w in [None, *of("about")] if a or w]
    gates += [(q, q) for q in of("practitioner")]
    pointers = [None, *of("points")]

    rows: list[tuple[int, int, tuple[str, ...]]] = []
    for hype, extra, (answerable, about), points in itertools.product(
        hypes, extras, gates, pointers
    ):
        right = surfaced = 0
        for c in cases:
            eid = str(c["evaluation_id"])
            action = route(
                compose(
                    base[eid],
                    variants[eid],
                    hype=hype,
                    extra_excl=extra,
                    answerable=answerable,
                    about=about,
                    points=points,
                )
            )["action"]
            right += action == c["human"]
            surfaced += (action != "drop") == (c["human"] != "drop")
        names = (hype, "+".join(extra), answerable, about, points)
        rows.append((right, surfaced, tuple(name or "v4" for name in names)))
    rows.sort(reverse=True)
    n = len(cases)
    print(f"\nroute() at default thresholds, top {args.top} of {len(rows)} combinations:")
    print(f"  {'action':>6} {'surf':>5}  hype / extra exclusion / answerable / about / points")
    for row_right, row_surfaced, labels in rows[: args.top]:
        print(f"  {row_right / n:6.0%} {row_surfaced / n:5.0%}  {' / '.join(labels)}")
    baseline = next(r for r in rows if set(r[2]) == {"v4"})
    print(f"  {baseline[0] / n:6.0%} {baseline[1] / n:5.0%}  (the original {args.base} run)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    runner = sub.add_parser("run")
    runner.add_argument("--catalogue", type=Path, required=True)
    runner.add_argument("--round", type=Path, required=True, help="the round directory")
    runner.add_argument("--output", type=Path, required=True)
    runner.add_argument("--dry-run", action="store_true")
    scorer = sub.add_parser("score")
    scorer.add_argument("--round", type=Path, required=True)
    scorer.add_argument("--variants", type=Path, nargs="+", required=True)
    scorer.add_argument("--top", type=int, default=15)
    scorer.add_argument("--arms", type=Path, help="base cells; default <round>/arms.json")
    scorer.add_argument("--base", default="jev:v4", help="arm whose answers the variants replace")
    scorer.add_argument("--only", nargs="*", help="restrict to these variant questions")
    args = parser.parse_args()
    run(args) if args.command == "run" else score(args)


if __name__ == "__main__":
    main()
