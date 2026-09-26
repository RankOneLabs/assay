"""Build and score a blind human label packet over the relevance arms run.

The arms grid showed every arm rejecting cases the stored labels call positive.
Two explanations survive it: the catalogue is wrong, or the stored labels answer
an older and broader question than the four-band rule the catalogue encodes.
Only a human reading the rule can separate those, so this module builds the
instrument for one to do it.

Design follows the Scout label-packets specification: seeded selection, a blind
projection checked against a field denylist on every case, a private answer key
the blind file never sees, and a reading declared and hashed before any label
exists.

The reviewer answers the catalogue's own two gating questions -- ``exclusion``
and ``band`` -- in the catalogue's own words. Their answers are one-hot encoded
into Jev's answer shapes and run through the same ``decide_argmax`` every arm
used, so the human traverses an identical code path rather than a parallel
scoring rule written for them.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

BAND_NAMES = ("out_of_scope", "building", "pointer", "substantive")

#: The three-way outcome the decision mapping now has to produce. Asked of the
#: reviewer directly rather than derived from the band, because whether a post is
#: worth a human's glance is a judgment about value, not about where its substance
#: sits. Keeping it separate is what lets the report score the deterministic
#: `pointer + has_link -> review` rule against what a human actually wanted.
DISPOSITIONS: tuple[tuple[str, str], ...] = (
    (
        "respond",
        "Worth replying to. The post gives you something specific to engage with.",
    ),
    (
        "review",
        "Worth a look, but not directly answerable — it points somewhere that may "
        "carry the substance, and you would want to click before deciding.",
    ),
    (
        "drop",
        "Not worth surfacing. Nothing here and nothing behind it.",
    ),
)

#: `substance` answers, in the order they are shown and in the order their tests
#: are applied: can you reply from the post's own words, can you open what it
#: points at, or neither. They route to respond / review / drop respectively.
#: There is no separate scope question — building versus operating was dropped
#: because it is unanswerable on a bare link, which is the case the rule exists
#: to get right. Topic is judged inside `in_post` instead: a reply has to be
#: about something, so a post nobody here would answer is `none`.
SUBSTANCE_NAMES = ("in_post", "pointer", "none")

#: Where each `substance` answer sends a post that cleared the exclusions. Scout
#: has no `review` state today — both non-drop answers surface — so this is the
#: outcome vocabulary the rule is written in, not a status enum.
SUBSTANCE_ROUTES: Mapping[str, str] = {
    "in_post": "respond",
    "pointer": "review",
    "none": "drop",
}

#: Carried from v2 unedited, where it retests at 90%. Named here so a typo in a
#: submitted label is rejected rather than silently dropping the post.
EXCLUSION_NAMES = (
    "non_english",
    "coding_assistant",
    "hardware",
    "funding_or_market",
    "event_promo",
    "hype",
    "none",
)

#: What a reviewer is asked for one case, normalised across question types so the
#: page can render any question set without knowing which questions it holds.
#: Flattening every question to one shape is what let the band question be
#: swapped out without touching the renderer.
QUESTION_ORDER_V3 = ("exclusion", "substance")
QUESTION_ORDER_V2 = ("exclusion", "band", "disposition")

#: Fields that must never survive the blind projection, whatever the policy says.
DENYLIST = (
    "human_label",
    "production_decision",
    "production_score",
    "arms",
    "decision",
    "band",
    "author_name",
    "author_handle",
    "url",
    "snapshot_id",
)

#: The only fields a reviewer sees. The band rule reads parent context, so it is
#: shown; every author identity is hidden, including the parent's, to keep this
#: packet on the content axis alone.
VISIBLE = ("case_id", "text", "parent_text")


class PacketError(RuntimeError):
    """A packet could not be built, projected or scored."""


@dataclass(frozen=True, slots=True)
class Stratum:
    """One named selection stratum and how many cases to draw from it."""

    key: str
    evaluation_ids: tuple[int, ...]
    take: int


@dataclass(frozen=True, slots=True)
class PacketCase:
    """One selected case, before the blind/private split."""

    case_id: int
    evaluation_id: int
    stratum: str


@dataclass(frozen=True, slots=True)
class Packet:
    """A built packet: the blind view, the private key, and the provenance."""

    name: str
    seed: str
    cases: tuple[PacketCase, ...]
    strata: Mapping[str, int] = field(default_factory=dict)


def _order_hash(seed: str, scope: str, evaluation_id: int) -> str:
    return hashlib.sha256(f"{seed}:{scope}:{evaluation_id}".encode()).hexdigest()


def arm_decisions(document: Mapping[str, Any], evaluation_id: int) -> dict[str, bool]:
    """Every arm's majority decision for one evaluation."""
    for case in document["cases"]:
        if case["evaluation_id"] != evaluation_id:
            continue
        return {
            arm_id: bool(arm_case["decision"])
            for arm_id, arm_case in case.get("arms", {}).items()
            if arm_case.get("complete")
        }
    raise PacketError(f"evaluation {evaluation_id} is not in the run")


def stratify(document: Mapping[str, Any]) -> dict[str, list[int]]:
    """Split the population by (stored label) x (how unanimous the arms were).

    ``crux`` is the stratum the packet exists for: stored-positive cases that
    every arm rejected. ``mirror`` is its opposite and guards against a reviewer
    simply ratifying whichever way the packet leans.
    """
    arms = list(document.get("arms", {}))
    buckets: dict[str, list[int]] = {}
    for case in document["cases"]:
        evaluation_id = int(case["evaluation_id"])
        decisions = [bool(case["arms"][arm]["decision"]) for arm in arms]
        label = bool(case["human_label"])
        if all(decisions):
            shape = "unanimous_yes"
        elif not any(decisions):
            shape = "unanimous_no"
        else:
            shape = "split"
        if label and shape == "unanimous_no":
            key = "crux"
        elif not label and shape == "unanimous_yes":
            key = "mirror"
        else:
            key = f"{shape}_{'positive' if label else 'negative'}"
        buckets.setdefault(key, []).append(evaluation_id)
    return buckets


def select_census(document: Mapping[str, Any], name: str, seed: str) -> Packet:
    """Take every case in the population, shuffled for display.

    A census needs no sampling plan, but it keeps the stratum tag so the report
    can still break results down by how the arms behaved — and so a repeat of an
    earlier packet's cases can be read as test-retest rather than new evidence.
    """
    buckets = stratify(document)
    stratum_of = {
        evaluation_id: key for key, ids in buckets.items() for evaluation_id in ids
    }
    shown = sorted(stratum_of, key=lambda e: _order_hash(seed, "display", e))
    return Packet(
        name=name,
        seed=seed,
        cases=tuple(
            PacketCase(
                case_id=index + 1,
                evaluation_id=evaluation_id,
                stratum=stratum_of[evaluation_id],
            )
            for index, evaluation_id in enumerate(shown)
        ),
        strata={key: len(ids) for key, ids in sorted(buckets.items())},
    )


def select_packet(
    document: Mapping[str, Any], name: str, seed: str, plan: Sequence[tuple[str, int]]
) -> Packet:
    """Draw ``take`` cases per stratum in seeded hash order, then shuffle for display.

    Selection order and display order use different hash scopes, so a case's
    position in the packet carries no information about which stratum it came
    from.
    """
    buckets = stratify(document)
    drawn: list[tuple[int, str]] = []
    for key, take in plan:
        available = buckets.get(key, [])
        if len(available) < take:
            raise PacketError(f"stratum {key!r} has {len(available)} cases, need {take}")
        ordered = sorted(available, key=lambda e: _order_hash(seed, key, e))
        drawn.extend((evaluation_id, key) for evaluation_id in ordered[:take])

    shown = sorted(drawn, key=lambda pair: _order_hash(seed, "display", pair[0]))
    return Packet(
        name=name,
        seed=seed,
        cases=tuple(
            PacketCase(case_id=index + 1, evaluation_id=evaluation_id, stratum=key)
            for index, (evaluation_id, key) in enumerate(shown)
        ),
        strata={key: take for key, take in plan},
    )


def select_fresh(
    populations: Mapping[str, Sequence[int]],
    name: str,
    seed: str,
    take: Sequence[tuple[str, int]],
    *,
    exclude: frozenset[int] = frozenset(),
) -> Packet:
    """Take the most recent ``n`` evaluations per project, then shuffle for display.

    Most recent means highest ``evaluation_id``. Posts already in an earlier
    grading round are skipped. The seed only sets display order; selection needs
    none. Each case's stratum is its project key.
    """
    drawn: list[tuple[int, str]] = []
    for key, n in take:
        available = sorted((e for e in populations.get(key, ()) if e not in exclude), reverse=True)
        if len(available) < n:
            raise PacketError(f"project {key!r} has {len(available)} fresh evaluations, need {n}")
        drawn.extend((evaluation_id, key) for evaluation_id in available[:n])

    shown = sorted(drawn, key=lambda pair: _order_hash(seed, "display", pair[0]))
    return Packet(
        name=name,
        seed=seed,
        cases=tuple(
            PacketCase(case_id=index + 1, evaluation_id=evaluation_id, stratum=key)
            for index, (evaluation_id, key) in enumerate(shown)
        ),
        strata={key: n for key, n in take},
    )


def blind_case(case_id: int, record: Mapping[str, Any]) -> dict[str, Any]:
    """Project one population record to what a reviewer may see.

    Raises if anything on the denylist survives, so the check runs per case
    rather than once at render time.
    """
    projected = {
        "case_id": case_id,
        "text": record["text"],
        "parent_text": record.get("parent_text"),
    }
    leaked = [key for key in DENYLIST if key in projected]
    if leaked:
        raise PacketError(f"blind projection leaked {leaked}")
    if set(projected) - set(VISIBLE):
        raise PacketError(f"blind projection carries unexpected fields: {set(projected)}")
    return projected


def rubric_card(questions: Mapping[str, Any]) -> dict[str, Any]:
    """The reviewer's instructions, verbatim from the catalogue.

    Nothing here is paraphrased. The arms answered this exact text, so a
    human/arm disagreement cannot be attributed to a rewording introduced for
    the packet.
    """
    band = questions["band"]
    exclusion = questions["exclusion"]
    return {
        "band": {
            "question": band["instructions"]["question"],
            "apply_in_order": list(band["instructions"]["apply_in_order"]),
            "note": band["instructions"]["note"],
            "levels": [
                {
                    "index": index,
                    "name": BAND_NAMES[index],
                    "summary": item["summary"],
                    "signals": list(item.get("signals", [])),
                }
                for index, item in enumerate(band["criteria"])
            ],
        },
        "exclusion": {
            "question": exclusion["instructions"]["question"],
            "judge": exclusion["instructions"]["judge"],
            "options": [
                {
                    "name": name,
                    "what": item["what"],
                    "not_for": item.get("not_for"),
                    "examples": list(item.get("examples") or []),
                }
                for name, item in exclusion["criteria"].items()
            ],
        },
        "disposition": {
            "question": "What should Scout do with this post?",
            "judge": (
                "Answer for what you would actually want, not what the band rule "
                "implies. This is the question the band rule is being measured "
                "against, so it has to be able to disagree with it."
            ),
            "options": [{"name": name, "what": what} for name, what in DISPOSITIONS],
        },
    }


def _option(
    name: str, what: str, *, not_for: str | None = None, value: str | None = None
) -> dict[str, Any]:
    """One radio button. ``value`` defaults to the name it is shown under."""
    return {"name": name, "what": what, "not_for": not_for, "value": value or name}


def _question(
    key: str,
    prompt: str,
    judge: str,
    options: Sequence[Mapping[str, Any]],
    *,
    value_type: str,
    asked_when: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One question, in the only shape the page knows how to render.

    ``value_type`` travels with the question because the page has to put the
    answer back into JSON with its original type — a band rung is an integer and
    a yes/no is a boolean, and neither survives a round trip as the string the
    radio actually carries. ``flag`` is a checkbox with no options: always a
    boolean, false until ticked.

    ``asked_when`` is ``{"question": <key>, "equals": <value>}`` or ``None`` for
    a question always asked. A question whose condition is unmet is not rendered
    and its answer is ``None`` in the record — absence, not a sentinel. This is
    what makes the questions a chain rather than a flat form: an excluded post is
    one decision, and `exclusion: hype` beside `substance: in_post` is a state
    the data can no longer express.
    """
    return {
        "key": key,
        "prompt": prompt,
        "judge": judge,
        "value_type": value_type,
        "asked_when": dict(asked_when) if asked_when else None,
        "options": list(options),
    }


def is_asked(question: Mapping[str, Any], answers: Mapping[str, Any]) -> bool:
    """Whether ``question`` applies, given the answers given so far.

    Mirrored in the page's JavaScript and in the server's validation. All three
    read the same `asked_when` off the packet, so the rule lives in the packet
    rather than in three hand-synced copies of it.
    """
    condition = question.get("asked_when")
    if not condition:
        return True
    return bool(answers.get(condition["question"]) == condition["equals"])


def substance_rubric_card(questions: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The reviewer's instructions for the substance rule, verbatim from v3.

    An ordered list rather than a keyed object: the page renders questions in the
    order given, and the order is load-bearing here. `exclusion` is asked first
    and ends the case when it fires; `substance` is only reached by a post that
    cleared it, which is what `asked_when` carries into the page and the server.
    """
    exclusion, substance = questions["exclusion"], questions["substance"]
    card = [
        _question(
            "exclusion",
            exclusion["instructions"]["question"],
            exclusion["instructions"]["judge"],
            [
                _option(name, item["what"], not_for=item.get("not_for"))
                for name, item in exclusion["criteria"].items()
            ],
            value_type="str",
        ),
        _question(
            "substance",
            substance["instructions"]["question"],
            substance["instructions"]["judge"],
            [
                _option(
                    name,
                    substance["criteria"][name]["what"],
                    not_for=substance["criteria"][name].get("not_for"),
                )
                for name in SUBSTANCE_NAMES
            ],
            value_type="str",
            asked_when=substance["asked_when"],
        ),
    ]
    #: v4's "need the thread" flag. A checkbox rather than a choice: unticked is
    #: an answer, so it never holds a case open.
    if "needs_thread" in questions:
        flag = questions["needs_thread"]
        card.append(
            _question(
                "needs_thread",
                flag["instructions"]["question"],
                flag["instructions"]["judge"],
                [],
                value_type="flag",
            )
        )
    return card


def as_questions(card: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Adapt the band-era keyed rubric to the ordered question list.

    Lets one renderer serve both question sets. The band's `apply_in_order` and
    its precedence note fold into the guidance paragraph, since the generic page
    has one prose slot per question — a fair trade for not carrying a second
    renderer for a question that is being retired.
    """
    band, exclusion, disposition = card["band"], card["exclusion"], card["disposition"]
    steps = " ".join(f"({index + 1}) {step}" for index, step in enumerate(band["apply_in_order"]))
    return [
        _question(
            "exclusion",
            exclusion["question"],
            exclusion["judge"],
            [
                _option(option["name"], option["what"], not_for=option.get("not_for"))
                for option in exclusion["options"]
            ],
            value_type="str",
        ),
        _question(
            "band",
            band["question"],
            f"Apply in order, stopping at the first that fits: {steps} {band['note']}",
            [
                _option(level["name"], level["summary"], value=str(level["index"]))
                for level in band["levels"]
            ],
            value_type="int",
        ),
        _question(
            "disposition",
            disposition["question"],
            disposition["judge"],
            [_option(option["name"], option["what"]) for option in disposition["options"]],
            value_type="str",
        ),
    ]


def route(exclusion: str, substance: str | None) -> str:
    """The rule, whole: respond, review or drop.

    An exclusion ends the case, which is why ``substance`` is ``None`` for one —
    it was never asked. Otherwise the answer routes straight through
    ``SUBSTANCE_ROUTES``. There is no other branch and no ordering subtlety
    beyond the chain itself; that is the point of it.

    The respond-versus-hold split *within* respond is not modelled: the census
    found the two groups indistinguishable by any property of the text, so it is
    a judgment about what we have to add rather than about the post.
    """
    if exclusion not in EXCLUSION_NAMES:
        raise PacketError(f"unknown exclusion {exclusion!r}")
    if exclusion != "none":
        if substance is not None:
            raise PacketError(f"substance answered on excluded post: {substance!r}")
        return "drop"
    if substance is None or substance not in SUBSTANCE_ROUTES:
        raise PacketError(f"unknown substance {substance!r}")
    return SUBSTANCE_ROUTES[substance]


def surfaced(exclusion: str, substance: str | None) -> bool:
    """Whether scout surfaces the post at all.

    Scout has no `review` state — `surfaced` is the one non-drop terminal status
    — so both `respond` and `review` collapse to True here. Kept separate from
    `route` so that when a review state exists, this is the only thing that
    changes.
    """
    return route(exclusion, substance) != "drop"


def human_answers(
    band_index: int, exclusion_name: str, questions: Mapping[str, Any]
) -> dict[str, Any]:
    """One-hot encode a reviewer's two answers into Jev's answer shapes."""
    names = list(questions["exclusion"]["criteria"])
    if exclusion_name not in names:
        raise PacketError(f"unknown exclusion {exclusion_name!r}")
    if not 0 <= band_index < len(BAND_NAMES):
        raise PacketError(f"band index out of range: {band_index}")
    return {
        "band": {
            "type": "score",
            "score": float(band_index),
            "probabilities": {
                str(index): (1.0 if index == band_index else 0.0)
                for index in range(len(BAND_NAMES))
            },
        },
        "exclusion": {
            "type": "choice",
            "choice": exclusion_name,
            "probabilities": {name: (1.0 if name == exclusion_name else 0.0) for name in names},
        },
    }


def eligibility_gate(answers: Mapping[str, Any]) -> bool:
    """The `agent_ops_relevance/v1` gate, over `band` and `exclusion` alone.

    `decide_argmax` reaches past the gate to derive a diagnostic band from the
    noul questions, which a reviewer answering two questions does not supply.
    `mappings.py` cannot be refactored to expose the gate on its own: its
    SHA-256 is recorded in the primary report's and the arms run's checksums,
    and editing it would invalidate published digests.

    So the gate is mirrored here rather than shared, and
    `test_gate_matches_decide_argmax_on_every_stored_answer_vector` asserts the
    two agree on every answer vector in the arms run. The equivalence is
    checked, not assumed.
    """
    def probabilities(name: str) -> Mapping[Any, float]:
        value = answers.get(name)
        if not isinstance(value, Mapping) or not isinstance(value.get("probabilities"), Mapping):
            raise PacketError(f"missing probabilities for {name}")
        return cast(Mapping[Any, float], value["probabilities"])

    band = probabilities("band")
    exclusion = probabilities("exclusion")
    p_substantive = float(band.get(3, band.get("3", band.get("substantive", 0.0))))
    p_exclusion = 1.0 - float(exclusion.get("none", 0.0))
    return p_substantive >= 0.5 and p_exclusion < 0.5


def human_decision(band_index: int, exclusion_name: str, questions: Mapping[str, Any]) -> bool:
    """Decide a reviewer's two answers through the same gate every arm passed."""
    return eligibility_gate(human_answers(band_index, exclusion_name, questions))


def plan_digest(reading: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical reading, recorded before labels exist."""
    canonical = json.dumps(reading, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()
