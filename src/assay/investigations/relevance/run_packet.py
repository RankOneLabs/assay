"""Build and score the blind relevance label packet.

``build`` writes four files into a private receipts directory: the blind
``packet.json`` and ``packet.html`` the reviewer opens, the private
``answer-key.json`` the blind pair never sees, and a ``PLAN.md`` carrying the
reading and its digest. ``score`` refuses to run unless the labels were saved
after the plan was written and carry its digest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from assay.investigations.relevance.catalogue import load_catalogue
from assay.investigations.relevance.packet import (
    BAND_NAMES,
    DISPOSITIONS,
    Packet,
    PacketError,
    arm_decisions,
    blind_case,
    human_decision,
    plan_digest,
    rubric_card,
    select_census,
    select_packet,
    stratify,
)
from assay.investigations.relevance.packet_html import render_packet_html

PACKET_NAME = "relevance-rubric-2026-09"
SEED = "assay-relevance-rubric-2026-09/v1"

CENSUS_NAME = "relevance-census-2026-09"
CENSUS_SEED = "assay-relevance-census-2026-09/v1"

#: Enriched for the crux stratum on purpose. Counts are reported per stratum;
#: the pooled agreement rate is not a population estimate.
PLAN: tuple[tuple[str, int], ...] = (
    ("crux", 15),
    ("unanimous_yes_positive", 5),
    ("mirror", 2),
    ("unanimous_no_negative", 4),
    ("split_positive", 2),
    ("split_negative", 2),
)

READING: dict[str, Any] = {
    "primary": {
        "stratum": "crux",
        "n": 15,
        "statistic": (
            "cases the reviewer places below `substantive`, or under a hard exclusion "
            "— that is, cases where the reviewer agrees with all five arms and against "
            "the stored label"
        ),
    },
    "thresholds": [
        {
            "at_least": 11,
            "conclusion": (
                "Rubric mismatch confirmed. The stored labels answer a broader question "
                "than the four-band rule, the arms are applying the rule correctly, and "
                "the arm-versus-production gap in the arms run is definitional rather "
                "than a quality gap. Relabelling all 79 becomes the path to an adoption "
                "number; the catalogue is not the blocker."
            ),
        },
        {
            "at_most": 4,
            "conclusion": (
                "The catalogue under-fires. Cases that are substantive under the rule as "
                "written are being rejected by every model that reads it, which is a "
                "criteria defect rather than a labelling artefact. Catalogue work is the "
                "priority and no relabel will rescue it."
            ),
        },
    ],
    "otherwise": (
        "Ambiguous. Neither explanation dominates at n=15; relabel all 79 before "
        "drawing any conclusion from the arms run."
    ),
}

CENSUS_READING: dict[str, Any] = {
    "purpose": (
        "Produce an adoption-grade label set for all 79 frozen evaluations under the "
        "agent-ops four-band rule, plus the three-way disposition the decision mapping "
        "now has to produce. These labels replace the stored ones, which answer the "
        "older and broader 'relevant in general' question."
    ),
    "primary": {
        "statistic": (
            "the reviewer's `disposition`, which is ground truth for the three-way "
            "outcome; `band` and `exclusion` are recorded alongside it so the rule's "
            "own gate can be scored against what the reviewer actually wanted"
        )
    },
    "declared_before_labelling": [
        {
            "name": "deterministic link rule",
            "claim": (
                "`pointer` + the post text contains a link approximates "
                "`disposition == review`. Reported as precision and recall against the "
                "reviewer's disposition. This is a measurement, not a threshold to pass."
            ),
        },
        {
            "name": "logistic fit",
            "claim": (
                "19 features over 79 rows is 4.2 rows per feature, so any fitted weight "
                "set is reported out-of-fold and is diagnostic only. No adoption claim "
                "may rest on an in-sample fit."
            ),
        },
        {
            "name": "test-retest",
            "claim": (
                "30 of these cases were labelled in `relevance-rubric-2026-09`. Their "
                "band agreement across the two sittings is the label noise floor and is "
                "reported before any model comparison. A low floor invalidates the "
                "comparison rather than the labels."
            ),
        },
    ],
}


def read_population(paths: Sequence[Path]) -> dict[int, dict[str, Any]]:
    records: dict[int, dict[str, Any]] = {}
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            records[int(record["evaluation_id"])] = record
    return records


def _digest(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True, slots=True)
class PacketIdentity:
    """What names one reading of one set of cases.

    Travels together everywhere a packet is written, so a second sitting over the
    same cases is never mistaken for the first.
    """

    sitting: str
    digest: str
    plan_digest: str


def packet_digest(
    blind: Sequence[Mapping[str, Any]], rubric: Mapping[str, Any], sitting: str
) -> str:
    """Identify a packet by what the reviewer is asked, not by how the page looks.

    Covers the questions and the sitting as well as the cases, both deliberately.
    A second reading of the same cases is a different packet: without ``sitting``
    a rebuild is byte-identical, and since the browser draft is keyed on this
    digest, the previous sitting's answers hydrate into the form and the retest
    reports perfect agreement having measured nothing.

    Just as deliberately excludes the rendered HTML, so that re-rendering the page
    with different JavaScript does not invalidate a draft already in progress.
    """
    return _digest({"cases": list(blind), "questions": rubric, "sitting": sitting})


def build(
    document: Mapping[str, Any],
    population: Mapping[int, Mapping[str, Any]],
    questions: Mapping[str, Any],
    output: Path,
    *,
    sitting: str,
    packet: Packet | None = None,
    reading: Mapping[str, Any] | None = None,
) -> Packet:
    packet = packet or select_packet(document, PACKET_NAME, SEED, PLAN)
    missing = [case.evaluation_id for case in packet.cases if case.evaluation_id not in population]
    if missing:
        raise PacketError(f"population is missing evaluations: {missing}")

    blind = [blind_case(case.case_id, population[case.evaluation_id]) for case in packet.cases]
    rubric = rubric_card(questions)
    identity = PacketIdentity(
        sitting=sitting,
        digest=packet_digest(blind, rubric, sitting),
        plan_digest=plan_digest(dict(reading or READING)),
    )
    digest, reading_digest = identity.digest, identity.plan_digest

    output.mkdir(parents=True, exist_ok=True)
    (output / "packet.json").write_text(
        json.dumps(
            {
                "format": "assay.label-packet/v1",
                "name": packet.name,
                "sitting": sitting,
                "digest": digest,
                "plan_digest": reading_digest,
                "cases": blind,
                "rubric": rubric,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (output / "packet.html").write_text(
        render_packet_html(packet.name, digest, reading_digest, blind, rubric), encoding="utf-8"
    )
    (output / "answer-key-private.json").write_text(
        json.dumps(
            {
                "format": "assay.label-packet-key/v1",
                "name": packet.name,
                "sitting": sitting,
                "digest": digest,
                "plan_digest": reading_digest,
                "seed": packet.seed,
                "strata": dict(packet.strata),
                "cases": [
                    {
                        "case_id": case.case_id,
                        "evaluation_id": case.evaluation_id,
                        "stratum": case.stratum,
                        "stored_label": bool(
                            next(
                                c
                                for c in document["cases"]
                                if c["evaluation_id"] == case.evaluation_id
                            )["human_label"]
                        ),
                        "production_decision": bool(
                            next(
                                c
                                for c in document["cases"]
                                if c["evaluation_id"] == case.evaluation_id
                            )["production_decision"]
                        ),
                        "arms": arm_decisions(document, case.evaluation_id),
                    }
                    for case in packet.cases
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    markdown = (
        _census_markdown(packet, identity)
        if reading is not None
        else _plan_markdown(packet, identity)
    )
    (output / "PLAN.md").write_text(markdown, encoding="utf-8")
    return packet


def _census_markdown(packet: Packet, identity: PacketIdentity) -> str:
    strata = "\n".join(f"| `{key}` | {count} |" for key, count in packet.strata.items())
    declared = "\n".join(
        f"- **{item['name']}** — {item['claim']}"
        for item in CENSUS_READING["declared_before_labelling"]
    )
    return f"""# {packet.name} — blind relabel census

Written {datetime.now(UTC).isoformat(timespec="seconds")}, before any label exists.

Sitting: `{identity.sitting}`

Packet digest: `{identity.digest}`

Reading digest: `{identity.plan_digest}`

Seed: `{packet.seed}`

## Purpose

{CENSUS_READING["purpose"]}

## Instrument

Every one of the {len(packet.cases)} frozen evaluations, in seeded display order.
Blind: post text and parent text only — no author, no URL, no stored label, no
production decision, no arm decision, and no indication that a case was seen in
an earlier packet.

Three questions per case. `exclusion` and `band` are the catalogue's own gating
questions in its own unedited words. `disposition` is new and is the ground truth
for the three-way outcome: **respond**, **review**, **drop**. It is asked directly
rather than derived from the band, because whether a post earns a human's glance
is a judgment about value, not about where its substance sits — and because the
band rule cannot be measured against a target derived from itself.

## Population shape

Strata are how the five arms behaved, carried for reporting only. They are not
shown to the reviewer and do not affect selection: this is a census, not a sample.

| stratum | cases |
| --- | ---: |
{strata}

## Declared before labelling

{declared}

## What these labels replace

The stored `human_label` on each evaluation answers "relevant in general" and is
retained for comparison only. After this census, `disposition` is the label of
record for the agent-ops project, and any figure scored against the stored labels
must say so explicitly.
"""


def _plan_markdown(packet: Packet, identity: PacketIdentity) -> str:
    strata = "\n".join(f"| `{key}` | {take} |" for key, take in packet.strata.items())
    thresholds = "\n".join(
        f"- **{'at least' if 'at_least' in t else 'at most'} "
        f"{t.get('at_least', t.get('at_most'))}** — {t['conclusion']}"
        for t in READING["thresholds"]
    )
    return f"""# {packet.name} — blind label packet

Written {datetime.now(UTC).isoformat(timespec="seconds")}, before any label exists.

Sitting: `{identity.sitting}`

Packet digest: `{identity.digest}`

Reading digest: `{identity.plan_digest}`

Seed: `{packet.seed}`

## Why

The arms run had every arm reject cases the stored labels call positive — 15 of
them unanimously, across two vendors, three models and two catalogue versions.
Either the catalogue is wrong or the stored labels answer an older, broader
question than the four-band rule. A human reading the rule separates those.

## Instrument

The reviewer answers the catalogue's own two gating questions, `exclusion` and
`band`, in the catalogue's own unedited words. Answers are one-hot encoded into
Jev's answer shapes and run through the same `decide_argmax` every arm used.

Blind: post text and parent text only. No author, no URL, no stored label, no
production decision, no arm decision. The projection is checked against a field
denylist per case, not once at render time.

## Strata

| stratum | cases |
| --- | ---: |
{strata}

These are sampling strata, not labels. The packet is deliberately enriched for
`crux`; counts are read per stratum and the pooled agreement rate is **not** a
population estimate.

## Reading, declared before labelling

Primary: of the {READING["primary"]["n"]} `crux` cases, count those where the
reviewer {READING["primary"]["statistic"]}.

{thresholds}

Otherwise — {READING["otherwise"]}
"""


def score(
    labels: Mapping[str, Any], key: Mapping[str, Any], questions: Mapping[str, Any]
) -> dict[str, Any]:
    if labels.get("plan_digest") != key.get("plan_digest"):
        raise PacketError("labels do not carry the plan digest they were collected under")
    by_case = {int(case["case_id"]): case for case in key["cases"]}

    rows: list[dict[str, Any]] = []
    for entry in labels["cases"]:
        case_id = int(entry["case_id"])
        if case_id not in by_case:
            raise PacketError(f"label for unknown case {case_id}")
        record = by_case[case_id]
        band_index = int(entry["band"])
        decision = human_decision(band_index, str(entry["exclusion"]), questions)
        arms = record["arms"]
        rows.append(
            {
                "case_id": case_id,
                "evaluation_id": record["evaluation_id"],
                "stratum": record["stratum"],
                "reviewer_band": BAND_NAMES[band_index],
                "reviewer_exclusion": entry["exclusion"],
                "reviewer_disposition": entry.get("disposition"),
                "reviewer_decision": decision,
                "stored_label": record["stored_label"],
                "production_decision": record["production_decision"],
                "arms": arms,
                "agrees_with_stored": decision == record["stored_label"],
                "agrees_with_arms_majority": decision == (sum(arms.values()) * 2 >= len(arms)),
                "note": entry.get("note"),
            }
        )

    crux = [row for row in rows if row["stratum"] == "crux"]
    with_arms = sum(1 for row in crux if not row["reviewer_decision"])
    fired = next(
        (
            threshold["conclusion"]
            for threshold in READING["thresholds"]
            if ("at_least" in threshold and with_arms >= threshold["at_least"])
            or ("at_most" in threshold and with_arms <= threshold["at_most"])
        ),
        READING["otherwise"],
    )
    strata: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = strata.setdefault(
            row["stratum"], {"n": 0, "agrees_with_stored": 0, "agrees_with_arms": 0}
        )
        bucket["n"] += 1
        bucket["agrees_with_stored"] += int(row["agrees_with_stored"])
        bucket["agrees_with_arms"] += int(row["agrees_with_arms_majority"])

    return {
        "format": "assay.label-packet-report/v1",
        "packet": key["name"],
        "packet_digest": key["digest"],
        "plan_digest": key["plan_digest"],
        "reviewer": labels.get("reviewer"),
        "saved_at": labels.get("saved_at"),
        "primary": {
            "stratum": "crux",
            "n": len(crux),
            "reviewer_sides_with_arms": with_arms,
            "conclusion": fired,
        },
        "strata": strata,
        "band_distribution": {
            name: sum(1 for row in rows if row["reviewer_band"] == name) for name in BAND_NAMES
        },
        "disposition_distribution": {
            name: sum(1 for row in rows if row["reviewer_disposition"] == name)
            for name, _ in DISPOSITIONS
        },
        "band_by_disposition": {
            band: {
                name: sum(
                    1
                    for row in rows
                    if row["reviewer_band"] == band and row["reviewer_disposition"] == name
                )
                for name, _ in DISPOSITIONS
            }
            for band in BAND_NAMES
        },
        "cases": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    builder = sub.add_parser("build")
    builder.add_argument("--run", type=Path, required=True)
    builder.add_argument("--population", type=Path, nargs="+", required=True)
    builder.add_argument("--catalogue", type=Path, required=True)
    builder.add_argument("--output", type=Path, required=True)
    builder.add_argument(
        "--sitting",
        required=True,
        help="names this reading of the cases; a repeat sitting must use a new name "
        "or it inherits the previous sitting's saved draft",
    )

    census = sub.add_parser("census", help="relabel the whole population")
    census.add_argument("--run", type=Path, required=True)
    census.add_argument("--population", type=Path, nargs="+", required=True)
    census.add_argument("--catalogue", type=Path, required=True)
    census.add_argument("--output", type=Path, required=True)
    census.add_argument(
        "--sitting",
        required=True,
        help="names this reading of the cases; a repeat sitting must use a new name "
        "or it inherits the previous sitting's saved draft",
    )

    scorer = sub.add_parser("score")
    scorer.add_argument("--labels", type=Path, required=True)
    scorer.add_argument("--key", type=Path, required=True)
    scorer.add_argument("--catalogue", type=Path, required=True)
    scorer.add_argument("--output", type=Path, default=None)

    args = parser.parse_args()
    questions = load_catalogue(args.catalogue).questions

    if args.command in ("build", "census"):
        document = json.loads(args.run.read_text(encoding="utf-8"))
        is_census = args.command == "census"
        packet = build(
            document,
            read_population(args.population),
            questions,
            args.output,
            sitting=args.sitting,
            packet=(
                select_census(document, CENSUS_NAME, CENSUS_SEED) if is_census else None
            ),
            reading=CENSUS_READING if is_census else None,
        )
        counts = stratify(document)
        print(f"strata: {({k: len(v) for k, v in sorted(counts.items())})}")
        print(f"{len(packet.cases)} cases into {args.output}")
        print(f"  open {args.output / 'packet.html'}")
        return

    report = score(
        json.loads(args.labels.read_text(encoding="utf-8")),
        json.loads(args.key.read_text(encoding="utf-8")),
        questions,
    )
    primary = report["primary"]
    if primary["n"]:
        print(f"crux: reviewer sides with the arms on {primary['reviewer_sides_with_arms']}"
              f"/{primary['n']}")
        print(f"\n{primary['conclusion']}\n")
    print(f"band:        {report['band_distribution']}")
    print(f"disposition: {report['disposition_distribution']}")
    print("\nband x disposition:")
    for band, counts in report["band_by_disposition"].items():
        if any(counts.values()):
            print(f"  {band:14s} {counts}")
    print()
    for stratum, counts in sorted(report["strata"].items()):
        print(f"  {stratum:24s} n={counts['n']:2d} "
              f"agrees-with-stored={counts['agrees_with_stored']:2d} "
              f"agrees-with-arms={counts['agrees_with_arms']:2d}")
    if args.output is not None:
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", "utf-8")
        print(f"\nwrote {args.output}")


if __name__ == "__main__":
    main()
