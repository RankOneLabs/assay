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


# Scope openers are tokens themselves so field-like expressions elsewhere never
# enter a declaration body. Parentheses and nested value braces mask members too.
_IDENTIFIER = r"[A-Za-z_$][\w$-]*"
_TOKEN = re.compile(
    r"(?P<type_body>\b(?:interface\s+[^{;]+|type\s+(?P<type_name>"
    + _IDENTIFIER
    + r")\s*(?:<[^>]*>)?\s*=\s*)\{)"
    r"|(?P<table>\bCREATE\s+TABLE\s+[^;(]+\()"
    r"|\btype\s+(?P<alias>" + _IDENTIFIER + r")\s*(?:<[^>]*>)?\s*="
    r'|\bALTER\s+TABLE\s+[^;\n]+?\s+ADD\s+(?:COLUMN\s+)?["`\[]?'
    r"(?P<alter>" + _IDENTIFIER + r")"
    r'|(?:readonly\s+)?["\']?(?P<field>' + _IDENTIFIER + r')["\']?\??\s*:'
    r'|["`\[]?(?P<column>' + _IDENTIFIER + r')["`\]]?'
    r"|(?P<punct>[{}(),;])|(?P<other>\S)",
    re.IGNORECASE,
)


def mirrored_state_count(patch: str, state_source_fields: Iterable[str]) -> int:
    """Count added type members, aliases and SQL columns matching the inventory.

    Context lines establish scope but never contribute declarations. Each hunk
    starts a fresh scope; absent declaration context cannot imply a type body.
    """
    names = {_spelling(name) for name in state_source_fields}
    count = 0
    scopes: list[str] = []
    for line in patch.splitlines():
        if line.startswith("@@"):
            scopes.clear()
        if not line.startswith(("+", " ")) or line.startswith("+++"):
            continue
        added = line.startswith("+")
        source = line[1:].split("//", 1)[0]
        boundary = True
        for match in _TOKEN.finditer(source):
            name: str | None = None
            if match["type_body"]:
                scopes.append("type")
                name = match["type_name"]
            elif match["table"]:
                scopes.append("table")
            elif match["alias"] or match["alter"]:
                name = match["alias"] or match["alter"]
            elif match["field"] and scopes and scopes[-1] == "type" and boundary:
                name = match["field"]
            elif match["column"] and scopes and scopes[-1] == "table" and boundary:
                if re.match(r"\s+[A-Za-z]+\b", source[match.end() :]):
                    name = match["column"]
                if name is not None and name.upper() in {
                    "PRIMARY",
                    "FOREIGN",
                    "UNIQUE",
                    "CONSTRAINT",
                    "CHECK",
                }:
                    name = None
            elif match["punct"] in {"{", "("}:
                scopes.append("other")
            elif match["punct"] in {"}", ")"} and scopes:
                scopes.pop()
            if added and name is not None and _spelling(name) in names:
                count += 1
            boundary = bool(
                match["type_body"] or match["table"] or match["punct"] in {";", ",", "{"}
            )
    return count
