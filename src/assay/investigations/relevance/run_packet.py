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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from assay.investigations.relevance.catalogue import load_catalogue
from assay.investigations.relevance.packet import (
    BAND_NAMES,
    Packet,
    PacketError,
    arm_decisions,
    blind_case,
    human_decision,
    plan_digest,
    rubric_card,
    select_packet,
    stratify,
)
from assay.investigations.relevance.packet_html import render_packet_html

PACKET_NAME = "relevance-rubric-2026-09"
SEED = "assay-relevance-rubric-2026-09/v1"

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


def build(
    document: Mapping[str, Any],
    population: Mapping[int, Mapping[str, Any]],
    questions: Mapping[str, Any],
    output: Path,
) -> Packet:
    packet = select_packet(document, PACKET_NAME, SEED, PLAN)
    missing = [case.evaluation_id for case in packet.cases if case.evaluation_id not in population]
    if missing:
        raise PacketError(f"population is missing evaluations: {missing}")

    blind = [blind_case(case.case_id, population[case.evaluation_id]) for case in packet.cases]
    digest = _digest(blind)
    reading_digest = plan_digest(READING)
    rubric = rubric_card(questions)

    output.mkdir(parents=True, exist_ok=True)
    (output / "packet.json").write_text(
        json.dumps(
            {
                "format": "assay.label-packet/v1",
                "name": packet.name,
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
    (output / "PLAN.md").write_text(
        _plan_markdown(packet, digest, reading_digest), encoding="utf-8"
    )
    return packet


def _plan_markdown(packet: Packet, digest: str, reading_digest: str) -> str:
    strata = "\n".join(f"| `{key}` | {take} |" for key, take in packet.strata.items())
    thresholds = "\n".join(
        f"- **{'at least' if 'at_least' in t else 'at most'} "
        f"{t.get('at_least', t.get('at_most'))}** — {t['conclusion']}"
        for t in READING["thresholds"]
    )
    return f"""# {packet.name} — blind label packet

Written {datetime.now(UTC).isoformat(timespec="seconds")}, before any label exists.

Packet digest: `{digest}`

Reading digest: `{reading_digest}`

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

    scorer = sub.add_parser("score")
    scorer.add_argument("--labels", type=Path, required=True)
    scorer.add_argument("--key", type=Path, required=True)
    scorer.add_argument("--catalogue", type=Path, required=True)
    scorer.add_argument("--output", type=Path, default=None)

    args = parser.parse_args()
    questions = load_catalogue(args.catalogue).questions

    if args.command == "build":
        document = json.loads(args.run.read_text(encoding="utf-8"))
        packet = build(document, read_population(args.population), questions, args.output)
        counts = stratify(document)
        print(f"available strata: {({k: len(v) for k, v in sorted(counts.items())})}")
        print(f"selected {len(packet.cases)} cases into {args.output}")
        print(f"  open {args.output / 'packet.html'}")
        return

    report = score(
        json.loads(args.labels.read_text(encoding="utf-8")),
        json.loads(args.key.read_text(encoding="utf-8")),
        questions,
    )
    primary = report["primary"]
    print(f"crux: reviewer sides with the arms on {primary['reviewer_sides_with_arms']}"
          f"/{primary['n']}")
    print(f"\n{primary['conclusion']}\n")
    for stratum, counts in sorted(report["strata"].items()):
        print(f"  {stratum:24s} n={counts['n']:2d} "
              f"agrees-with-stored={counts['agrees_with_stored']:2d} "
              f"agrees-with-arms={counts['agrees_with_arms']:2d}")
    if args.output is not None:
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", "utf-8")
        print(f"\nwrote {args.output}")


if __name__ == "__main__":
    main()
