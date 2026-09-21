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

from typesafe_relevance.catalogue import load_catalogue
from typesafe_relevance.packet import (
    BAND_NAMES,
    DISPOSITIONS,
    EXCLUSION_NAMES,
    SUBSTANCE_NAMES,
    Packet,
    PacketError,
    arm_decisions,
    as_questions,
    blind_case,
    human_decision,
    plan_digest,
    route,
    rubric_card,
    select_census,
    select_packet,
    stratify,
    substance_rubric_card,
)
from typesafe_relevance.packet_html import (
    FORMATS_V1,
    FORMATS_V2,
    render_packet_html,
)

PACKET_NAME = "relevance-rubric-2026-09"
SEED = "assay-relevance-rubric-2026-09/v1"

CENSUS_NAME = "relevance-census-2026-09"
CENSUS_SEED = "assay-relevance-census-2026-09/v1"

SUBSTANCE_NAME = "relevance-substance-2026-09"

#: A different display order from the census on purpose. If sitting two showed the
#: same cases in the same sequence, an order effect would replicate along with the
#: answers and read as agreement.
SUBSTANCE_SEED = "assay-relevance-substance-2026-09/v1"

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


SUBSTANCE_READING: dict[str, Any] = {
    "purpose": (
        "Label all 79 frozen evaluations under the substance rule — an exclusion ends "
        "the case, and anything that clears it is asked where its substance sits: "
        "in_post (respond), pointer (review), or none (drop). This sitting produces "
        "the labels of record under the new schema and cross-walks them against the "
        "census `band`. It does not measure the new question's retest floor: `band` "
        "and `substance` are different questions, so reading one after the other is a "
        "cross-walk, not a repeat. The floor needs a third sitting of this same packet "
        "and is declared here so that nobody later reports the cross-walk as one."
    ),
    "primary": {
        "statistic": (
            "Concordance with the census on the 51 cases where `band` maps to "
            "`substance` unambiguously: the 32 `substantive` cases should be "
            "`in_post`, and the 19 `pointer` cases should be `pointer`. The 16 "
            "`building` cases are excluded from the primary because `band` applied in "
            "order, so `building` absorbed both kinds — a building post with a claim "
            "and a bare link about building both scored `building`, and neither maps "
            "to one substance answer. The 12 `out_of_scope` cases are excluded "
            "because 9 of them are caught by an exclusion first and never reach the "
            "question."
        ),
        "n": 51,
    },
    "thresholds": [
        {
            "at_least": 43,
            "conclusion": (
                "The new question preserves the distinction `band` was drawing where "
                "`band` was unambiguous, while dropping the rungs that fused two axes. "
                "The published census numbers cross-walk, and a third sitting for the "
                "floor is worth running."
            ),
        },
        {
            "at_most": 33,
            "conclusion": (
                "The new question is measuring something `band` was not. That is not "
                "automatically a failure — `band` retested at 63%, so a large part of "
                "this gap may be `band`'s own noise rather than a change of construct. "
                "It does mean no census number may be carried forward onto the new "
                "schema, and the notes column is the first place to look for why."
            ),
        },
    ],
    "otherwise": (
        "Ambiguous. Report the figure, carry no census number forward without saying "
        "which cases moved, and run the third sitting before resting anything on it."
    ),
    "declared_before_labelling": [
        {
            "name": "substantive -> in_post concordance",
            "claim": (
                "The headline half. A post whose own words carried a point under "
                "`band` should be answerable from its own words under `substance`. "
                "Disagreement here is the new question rejecting `band`'s top rung."
            ),
        },
        {
            "name": "pointer -> pointer concordance",
            "claim": (
                "The other half, and the one the schema was rebuilt for. `band` put "
                "`pointer` below `substantive` and resolved the overlap in a "
                "precedence note; `substance` resolves it in the question itself — a "
                "link does not make a post a pointer, being unable to reply without "
                "it does. If this half moves and the other does not, that note was "
                "the defect."
            ),
        },
        {
            "name": "exclusion retest",
            "claim": (
                "A genuine retest — same question, third reading, carried from v2 "
                "unedited. Held at 90% across the first two sittings. This is the "
                "control: if it moves materially, the sitting is not comparable to "
                "the census and the concordance figure means less than it appears to."
            ),
        },
        {
            "name": "route distribution",
            "claim": (
                "How many of 79 route to respond, review and drop, against the "
                "census's 22/22/35 and production's 75% surfaced. Descriptive, not a "
                "test — recorded before labelling so it cannot be chosen afterwards."
            ),
        },
        {
            "name": "off-topic leakage",
            "claim": (
                "3 of the census's 12 `out_of_scope` cases carried `exclusion: none`, "
                "so with `band` and `scope` both gone nothing catches them but the "
                "`in_post` test's requirement that a reply be about agent work. Those "
                "3 should answer `none`. If they answer `in_post`, that test is not "
                "carrying the topic judgment and an eighth exclusion is needed."
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
    blind: Sequence[Mapping[str, Any]],
    rubric: Sequence[Mapping[str, Any]] | Mapping[str, Any],
    sitting: str,
) -> str:
    """Identify a packet by what the reviewer is asked, not by how the page looks.

    Covers the questions and the sitting as well as the cases, both deliberately.
    A second reading of the same cases is a different packet: without ``sitting``
    a rebuild is byte-identical, and since the browser draft is keyed on this
    digest, the previous sitting's answers hydrate into the form and the retest
    reports perfect agreement having measured nothing.

    Just as deliberately excludes the rendered HTML, so that re-rendering the page
    with different JavaScript does not invalidate a draft already in progress.

    ``rubric`` accepts either shape: the ordered question list a page is built
    from, or the band-era keyed card, which older tests still hash directly.
    """
    questions = list(rubric) if isinstance(rubric, Sequence) else rubric
    return _digest({"cases": list(blind), "questions": questions, "sitting": sitting})


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
    #: Which question set the catalogue carries decides everything downstream —
    #: what the page asks, what the labels are stamped, and what the server accepts.
    substance = "substance" in questions
    rubric = substance_rubric_card(questions) if substance else as_questions(rubric_card(questions))
    formats = FORMATS_V2 if substance else FORMATS_V1
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
        render_packet_html(packet.name, digest, reading_digest, blind, rubric, formats=formats),
        encoding="utf-8",
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
    if substance:
        markdown = _substance_markdown(packet, identity)
    elif reading is not None:
        markdown = _census_markdown(packet, identity)
    else:
        markdown = _plan_markdown(packet, identity)
    (output / "PLAN.md").write_text(markdown, encoding="utf-8")
    return packet


def _substance_markdown(packet: Packet, identity: PacketIdentity) -> str:
    strata = "\n".join(f"| `{key}` | {count} |" for key, count in packet.strata.items())
    declared = "\n".join(
        f"- **{item['name']}** — {item['claim']}"
        for item in SUBSTANCE_READING["declared_before_labelling"]
    )
    primary = SUBSTANCE_READING["primary"]
    thresholds = "\n".join(
        f"- **{'at least' if 'at_least' in item else 'at most'} "
        f"{item.get('at_least', item.get('at_most'))} of {primary['n']}** — {item['conclusion']}"
        for item in SUBSTANCE_READING["thresholds"]
    )
    return f"""# {packet.name} — the substance rule, sitting two

Written {datetime.now(UTC).isoformat(timespec="seconds")}, before any label exists.

Sitting: `{identity.sitting}`

Packet digest: `{identity.digest}`

Reading digest: `{identity.plan_digest}`

Seed: `{packet.seed}`

## Purpose

{SUBSTANCE_READING["purpose"]}

## The rule being tested

```
exclusion != none                      -> drop
exclusion == none  AND  in_post        -> respond
exclusion == none  AND  pointer        -> review
exclusion == none  AND  none           -> drop
```

A chain, not a conjunction: an exclusion ends the case, and `substance` is only
asked of a post that cleared it. No other branch and no ordering subtlety beyond
the chain itself.

Scout has no `review` state — `surfaced` is its one non-drop terminal status — so
`respond` and `review` both surface today. The split is recorded because it is
the decision being studied, not because a status exists for it.

Whether a surfaced post gets a reply is decided downstream with our own context
in hand; it is not a property of the post and is deliberately not modelled here.

`review` here can only mean "follow the pointer". The other reason to want a
second look — knowing who posted it — is unreachable by construction: this packet
is blind to the author. That is a known gap, not an oversight.

## Instrument

Every one of the {len(packet.cases)} frozen evaluations, in a display order seeded
differently from the census so an order effect cannot replicate along with the
answers. Blind: post text and parent text only — no author, no URL, no stored
label, no production decision, no arm decision, and no indication that a case
carries an earlier answer.

Two questions per case, asked as a chain: `exclusion` always, and `substance`
only when `exclusion` is `none`. An excluded post is one decision. `band` is
**not** asked — it is being retired, and a third reading of a question under
withdrawal buys nothing. `exclusion` is carried over from v2 unedited, where it
retests at 90%, and is the control for whether this sitting is comparable to the
census at all.

A free-text note per case, optional, for anything the two questions cannot
carry. Notes stay in run-receipts and are stripped from published evidence.

## Primary statistic

{primary["statistic"]}

{thresholds}

Otherwise: {SUBSTANCE_READING["otherwise"]}

## Population shape

| stratum | cases |
| --- | ---: |
{strata}

## Declared before labelling

{declared}
"""


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
    labels: Mapping[str, Any],
    key: Mapping[str, Any],
    questions: Mapping[str, Any],
    *,
    census: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Score a sitting, dispatching on which questions its labels answer.

    ``/v2`` labels carry `substance`; ``/v1`` labels carry `band`.
    The band path is kept rather than deleted with the question: it is what
    reproduces `relevance-census-2026-09`, and every figure in that run's
    published RESULTS.md is computed from its output. Retiring a question from the
    instrument is not a reason to lose the ability to read data already collected
    under it.
    """
    if labels.get("format") == FORMATS_V2.labels:
        return score_substance(labels, key, census=census)
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


def score_substance(
    labels: Mapping[str, Any],
    key: Mapping[str, Any],
    *,
    census: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Score a substance-rule sitting.

    No catalogue is needed: the rule is a two-step chain over answers the reviewer
    gave directly, not a gate reconstructed from one-hot probability vectors. That
    is most of why it replaced the band question.

    ``census`` is the merged census labels, optional. When given, the report
    carries the cross-walk against `band` that `SUBSTANCE_READING` pre-registers
    as the primary statistic. It is a cross-walk and never a retest: `band` and
    `substance` are different questions.
    """
    if labels.get("plan_digest") != key.get("plan_digest"):
        raise PacketError("labels do not carry the plan digest they were collected under")
    by_case = {int(case["case_id"]): case for case in key["cases"]}

    rows: list[dict[str, Any]] = []
    for entry in labels["cases"]:
        case_id = int(entry["case_id"])
        if case_id not in by_case:
            raise PacketError(f"label for unknown case {case_id}")
        record = by_case[case_id]
        exclusion = str(entry["exclusion"])
        raw = entry.get("substance")
        substance = None if raw is None else str(raw)
        outcome = route(exclusion, substance)
        decision = outcome != "drop"
        arms = record["arms"]
        rows.append(
            {
                "case_id": case_id,
                "evaluation_id": record["evaluation_id"],
                "stratum": record["stratum"],
                "reviewer_exclusion": exclusion,
                "reviewer_substance": substance,
                "reviewer_route": outcome,
                "reviewer_decision": decision,
                "stored_label": record["stored_label"],
                "production_decision": record["production_decision"],
                "arms": arms,
                "agrees_with_stored": decision == record["stored_label"],
                "agrees_with_arms_majority": decision == (sum(arms.values()) * 2 >= len(arms)),
                "note": entry.get("note"),
            }
        )

    surfaced_rows = [row for row in rows if row["reviewer_decision"]]
    report: dict[str, Any] = {
        "format": "assay.label-packet-report/v2",
        "packet": key["name"],
        "packet_digest": key["digest"],
        "plan_digest": key["plan_digest"],
        "reviewer": labels.get("reviewer"),
        "saved_at": labels.get("saved_at"),
        "surfaced": {
            "surfaced": len(surfaced_rows),
            "n": len(rows),
            "rate": round(len(surfaced_rows) / len(rows), 4) if rows else 0.0,
        },
        "route_distribution": {
            name: sum(1 for row in rows if row["reviewer_route"] == name)
            for name in ("respond", "review", "drop")
        },
        "exclusion_distribution": {
            name: sum(1 for row in rows if row["reviewer_exclusion"] == name)
            for name in EXCLUSION_NAMES
        },
        #: `null` counts the posts an exclusion ended, which is the only way the
        #: question goes unanswered. It is reported rather than dropped so the
        #: three substance counts and the exclusion counts reconcile to n.
        "substance_distribution": {
            **{
                name: sum(1 for row in rows if row["reviewer_substance"] == name)
                for name in SUBSTANCE_NAMES
            },
            "null": sum(1 for row in rows if row["reviewer_substance"] is None),
        },
        "cases": rows,
    }
    if census is not None:
        report["census_crosswalk"] = _crosswalk(rows, census)
    return report


#: How the census `band` maps onto a `substance` answer where it maps at all.
#: `building` is absent on purpose: `band` applied in order, so it absorbed both a
#: building post with a claim and a bare link about building, and neither maps to
#: one answer. `out_of_scope` is absent because 9 of its 12 census cases are
#: caught by an exclusion first and never reach the question.
BAND_TO_SUBSTANCE: Mapping[str, str] = {
    "substantive": "in_post",
    "pointer": "pointer",
}


def _crosswalk(
    rows: Sequence[Mapping[str, Any]], census: Mapping[str, Any]
) -> dict[str, Any]:
    """Cross-walk this sitting's `substance` against the census `band`.

    Restricted to the bands that map unambiguously, which is what the primary
    statistic is declared over. Every band is still tabulated below it, so the
    cases excluded from the primary are visible rather than silently missing.
    """
    band_of = {
        int(case["evaluation_id"]): str(case["band"]) for case in census["cases"]
    }
    matched = [row for row in rows if int(row["evaluation_id"]) in band_of]
    scored = [
        row for row in matched if band_of[int(row["evaluation_id"])] in BAND_TO_SUBSTANCE
    ]
    agree = [
        row
        for row in scored
        if row["reviewer_substance"] == BAND_TO_SUBSTANCE[band_of[int(row["evaluation_id"])]]
    ]
    return {
        "n": len(scored),
        "agree": len(agree),
        "rate": round(len(agree) / len(scored), 4) if scored else 0.0,
        "matched_cases": len(matched),
        "by_band": {
            band: {
                name: sum(
                    1
                    for row in matched
                    if band_of[int(row["evaluation_id"])] == band
                    and (row["reviewer_substance"] or "null") == name
                )
                #: "null" rather than None: the report is written with
                #: `sort_keys`, which cannot order None against a str.
                for name in (*SUBSTANCE_NAMES, "null")
            }
            for band in BAND_NAMES
        },
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

    substance = sub.add_parser(
        "substance", help="label the whole population under the substance rule"
    )
    substance.add_argument("--run", type=Path, required=True)
    substance.add_argument("--population", type=Path, nargs="+", required=True)
    substance.add_argument("--catalogue", type=Path, required=True)
    substance.add_argument("--output", type=Path, required=True)
    substance.add_argument(
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
    #: The merged census labels. Optional, and only read by the substance path,
    #: where it supplies the pre-registered cross-walk against `band`.
    scorer.add_argument("--census", type=Path, default=None)

    args = parser.parse_args()
    questions = load_catalogue(args.catalogue).questions

    if args.command in ("build", "census", "substance"):
        document = json.loads(args.run.read_text(encoding="utf-8"))
        selected, reading = {
            "build": (None, None),
            "census": (
                lambda: select_census(document, CENSUS_NAME, CENSUS_SEED),
                CENSUS_READING,
            ),
            "substance": (
                lambda: select_census(document, SUBSTANCE_NAME, SUBSTANCE_SEED),
                SUBSTANCE_READING,
            ),
        }[args.command]
        packet = build(
            document,
            read_population(args.population),
            questions,
            args.output,
            sitting=args.sitting,
            packet=selected() if selected else None,
            reading=reading,
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
        census=(
            json.loads(args.census.read_text(encoding="utf-8"))
            if args.census is not None
            else None
        ),
    )
    if report["format"] == "assay.label-packet-report/v2":
        print(f"surfaced: {report['surfaced']['surfaced']}/{report['surfaced']['n']} "
              f"= {report['surfaced']['rate']:.0%}")
        print(f"route:     {report['route_distribution']}")
        print(f"substance: {report['substance_distribution']}")
        print(f"exclusion: {report['exclusion_distribution']}")
        walk = report.get("census_crosswalk")
        if walk is not None:
            print(f"\ncensus cross-walk: {walk['agree']}/{walk['n']} = {walk['rate']:.0%}")
            for band, counts in walk["by_band"].items():
                print(f"  {band:14s} {counts}")
        if args.output is not None:
            args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", "utf-8")
        return
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
