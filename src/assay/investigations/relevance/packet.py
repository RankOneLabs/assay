"""Build and score a blind human label packet over the relevance arms run.

The arms grid showed every arm rejecting cases the stored labels call positive.
Two explanations survive it: the catalogue is wrong, or the stored labels answer
an older and broader question than the four-band rule the catalogue encodes.
Only a human reading the rule can separate those, so this module builds the
instrument for one to do it.

Design follows ``scout/comms/label-packets-spec.md``: seeded selection, a blind
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
                    "examples": list(item.get("examples", [])),
                }
                for name, item in exclusion["criteria"].items()
            ],
        },
    }


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
