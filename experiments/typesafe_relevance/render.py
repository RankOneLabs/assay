"""Render a catalogue as an LLM prompt and normalize the reply to Jev's answer shape.

The point of this module is that the Typesafe arm and the LLM arms answer the
*same* questions. Both the prompt and the response schema are derived from the
one loaded catalogue document, so a wording change cannot reach one backend and
not the other.

Normalized answers use the shapes ``typesafe-sdk`` returns, so
``mappings.decide_argmax`` and ``mappings.derive_band`` run unchanged over
either backend's output:

    noul   {"type": "noul",   "noul": p}
    choice {"type": "choice", "choice": label, "confidence": c, "probabilities": {...}}
    score  {"type": "score",  "score": s, "confidence": c, "probabilities": {"0": p, ...}}

``confidence`` is not something an LLM reports the way Jev does; here it is the
top probability. No decision mapping reads it — ``decide_argmax`` uses only the
``band`` and ``exclusion`` probability maps — so the choice of definition cannot
move a verdict. It travels for display and for parity of shape only.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

PROMPT_PREAMBLE = """\
You answer atomic classification questions about a single social media post.

You will be given a state object describing the post, then a numbered list of
questions. Answer every question independently from the same state. Judge each
question only by its own criteria; do not let your answer to one question
constrain another.

Answer types:

- noul: return one probability in [0,1] that the answer is yes.
- choice: return a probability for every listed option. They must sum to 1.
- score: return a probability for every listed level, keyed by level number.
  They must sum to 1.

Report genuine uncertainty as spread probability. Do not round to 0 or 1 unless
the evidence in the state is actually decisive.

Return only JSON matching the required schema."""


class RenderError(ValueError):
    """A catalogue cannot be rendered for an LLM backend."""


def _lines(label: str, value: Any, indent: str) -> list[str]:
    """Flatten one criteria field into prompt lines; strings, lists and maps."""
    if value is None:
        return []
    if isinstance(value, str):
        return [f"{indent}{label}: {value.strip()}"]
    if isinstance(value, Sequence):
        return [f"{indent}{label}:"] + [f"{indent}  - {str(item).strip()}" for item in value]
    if isinstance(value, Mapping):
        return [f"{indent}{label}:"] + [
            f"{indent}  {key}: {str(item).strip()}" for key, item in value.items()
        ]
    return [f"{indent}{label}: {value}"]


def _instruction_lines(instructions: Any) -> list[str]:
    if isinstance(instructions, str):
        return [f"  {instructions.strip()}"]
    if isinstance(instructions, Mapping):
        out: list[str] = []
        for key, value in instructions.items():
            out.extend(_lines(str(key), value, "  "))
        return out
    raise RenderError(f"unsupported instructions type: {type(instructions)!r}")


def _criteria_lines(question: Mapping[str, Any]) -> list[str]:
    kind = question["type"]
    criteria = question["criteria"]
    out: list[str] = []
    if kind == "score":
        out.append("  levels, lowest to highest:")
        for level, item in enumerate(criteria):
            out.append(f"    {level}. {str(item['summary']).strip()}")
            for signal in item.get("signals", ()):
                out.append(f"       - {str(signal).strip()}")
        return out
    out.append("  options:" if kind == "choice" else "  criteria:")
    for name, item in criteria.items():
        out.append(f"    {name}:")
        for field in ("what", "not_for"):
            out.extend(_lines(field, item.get(field), "      "))
        out.extend(_lines("examples", item.get("examples"), "      "))
    return out


def render_prompt(catalogue_questions: Mapping[str, Mapping[str, Any]]) -> str:
    """Render the catalogue's questions as a numbered system prompt."""
    blocks: list[str] = [PROMPT_PREAMBLE, "", "Questions:"]
    for number, (question_id, question) in enumerate(catalogue_questions.items(), start=1):
        blocks.append("")
        blocks.append(f"{number}. {question_id} ({question['type']})")
        blocks.extend(_instruction_lines(question["instructions"]))
        blocks.extend(_criteria_lines(question))
    return "\n".join(blocks)


def _probability_map(names: Sequence[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {name: {"type": "number"} for name in names},
        "required": list(names),
        "additionalProperties": False,
    }


def answer_schema(catalogue_questions: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Build the strict JSON schema mirroring this catalogue's answer domains."""
    properties: dict[str, Any] = {}
    for question_id, question in catalogue_questions.items():
        kind = question["type"]
        if kind == "noul":
            properties[question_id] = {"type": "number"}
        elif kind == "choice":
            properties[question_id] = _probability_map(list(question["criteria"]))
        elif kind == "score":
            levels = [str(index) for index in range(len(question["criteria"]))]
            properties[question_id] = _probability_map(levels)
        else:
            raise RenderError(f"unsupported question type: {kind!r}")
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _clamp(value: Any) -> float:
    number = float(value)
    if number != number:  # NaN
        raise RenderError("answer probability is NaN")
    return min(1.0, max(0.0, number))


def _renormalized(raw: Mapping[str, Any], names: Sequence[str]) -> dict[str, float]:
    values = {name: _clamp(raw.get(name, 0.0)) for name in names}
    total = sum(values.values())
    if total <= 0:
        raise RenderError("answer probabilities sum to zero")
    return {name: value / total for name, value in values.items()}


def normalize_answers(
    payload: Mapping[str, Any], catalogue_questions: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    """Convert a mirror-schema LLM reply into Jev-shaped answers.

    Raises RenderError on any missing question, so a short reply is reported as
    an arm failure rather than silently scored as a negative.
    """
    answers: dict[str, Any] = {}
    for question_id, question in catalogue_questions.items():
        if question_id not in payload:
            raise RenderError(f"reply is missing question: {question_id}")
        raw = payload[question_id]
        kind = question["type"]
        if kind == "noul":
            answers[question_id] = {"type": "noul", "noul": _clamp(raw)}
            continue
        if not isinstance(raw, Mapping):
            raise RenderError(f"{question_id}: expected a probability object")
        if kind == "choice":
            names = list(question["criteria"])
            probabilities = _renormalized(raw, names)
            label = max(probabilities, key=probabilities.__getitem__)
            answers[question_id] = {
                "type": "choice",
                "choice": label,
                "confidence": probabilities[label],
                "probabilities": probabilities,
            }
            continue
        levels = [str(index) for index in range(len(question["criteria"]))]
        probabilities = _renormalized(raw, levels)
        answers[question_id] = {
            "type": "score",
            "score": sum(int(level) * value for level, value in probabilities.items()),
            "confidence": max(probabilities.values()),
            "probabilities": probabilities,
        }
    return answers


def render_state(state: Mapping[str, Any]) -> str:
    """Render the state object as the user turn."""
    return json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True)
