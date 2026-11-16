"""Reporting measures kept separate from fact scoring."""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from code_extension.fact_shapes.attempts import Assessment
from code_extension.fact_shapes.outcome import AttemptStatus, Missed, Scored
from code_extension.reachability import _spelling


@dataclass(frozen=True)
class CompletionClaim:
    claimed_completion: bool
    missed_any: bool
    completion_claim: bool


def completion_claim(status: AttemptStatus, verdict: Assessment | None) -> CompletionClaim | None:
    if not isinstance(status, Scored):
        return None
    claimed = verdict == "complete"
    missed = any(isinstance(fact, Missed) for fact in status.facts.values())
    return CompletionClaim(claimed, missed, claimed and missed)


_DECLARATION = re.compile(
    r"\btype\s+([A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\s*="
    r'|\bADD\s+COLUMN\s+["`\[]?([\w-]+)'
    r'|(?:^|[;{,])\s*(?:readonly\s+)?["\']?([A-Za-z_$][\w$-]*)["\']?\??\s*:',
    re.IGNORECASE,
)


def mirrored_state_count(patch: str, state_source_fields: Iterable[str]) -> int:
    """Count added declarations matching inventory field names, once per declaration."""
    names = {_spelling(name) for name in state_source_fields}
    count = 0
    value_object_depth = 0
    for line in patch.splitlines():
        if line.startswith(("+++", "---", "-")):
            continue
        source = line[1:] if line.startswith(("+", " ")) else line
        # Object values have the same colon spelling as type fields. Context
        # retained in the hunk distinguishes them, including multiline values.
        if re.search(r"\b(?:const|let|var)\s+.*=\s*\{", source):
            value_object_depth = max(0, source.count("{") - source.count("}"))
            continue
        if value_object_depth:
            value_object_depth += source.count("{") - source.count("}")
            continue
        if line.startswith("+"):
            count += sum(
                _spelling(next(name for name in match if name)) in names
                for match in _DECLARATION.findall(source)
            )
    return count
