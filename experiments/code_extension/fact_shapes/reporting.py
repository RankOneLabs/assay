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
_QUOTED = r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`"
_COMMENT = r"/\*[\s\S]*?(?:\*/|$)|//[^\n]*|--[^\n]*"
_LEXICAL = re.compile(f"(?P<quoted>{_QUOTED})|(?P<comment>{_COMMENT})")
_TOKEN = re.compile(
    f"(?P<quoted>{_QUOTED})"
    r"|(?P<type_body>\b(?:interface\s+[^{;]+|type\s+(?P<type_name>"
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


def _count_declarations(source: str, added: list[bool], names: set[str]) -> int:
    # Mask comments before matching headers, which can span whitespace. Keep
    # offsets and newlines intact so added-line attribution remains exact;
    # quoted tokens protect comment-like text inside strings.
    source = _LEXICAL.sub(
        lambda match: re.sub(r"[^\n]", " ", match[0]) if match["comment"] else match[0], source
    )
    scopes: list[str] = []
    count = 0
    boundary = True
    end = 0
    for match in _TOKEN.finditer(source):
        boundary = boundary or "\n" in source[end : match.start()]
        end = match.end()
        name: str | None = None
        offset = match.start()
        if match["type_body"]:
            scopes.append("type")
            name = match["type_name"]
            if name is not None:
                offset = match.start("type_name")
        elif match["table"]:
            scopes.append("table")
        elif match["alias"] or match["alter"]:
            group = "alias" if match["alias"] else "alter"
            name = match[group]
            offset = match.start(group)
        elif match["field"] and scopes and scopes[-1] == "type" and boundary:
            name = match["field"]
            offset = match.start("field")
        elif match["quoted"] and scopes and boundary:
            # Quoted member/column names are declarations; their contents are
            # never scanned as code. Backticks are template values, not names.
            quoted = match["quoted"]
            is_member = scopes[-1] == "type" and re.match(r"\s*\??:", source[end:])
            is_column = scopes[-1] == "table" and re.match(r"\s+[A-Za-z]+\b", source[end:])
            if not quoted.startswith("`") and (is_member or is_column):
                name = quoted[1:-1]
        elif match["column"] and scopes and scopes[-1] == "table" and boundary:
            if re.match(r"\s+[A-Za-z]+\b", source[end:]):
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
            # An object nested in a type body is another object type. Function
            # parameter parentheses and ordinary expression braces mask fields.
            scopes.append(
                "type" if match["punct"] == "{" and scopes and scopes[-1] == "type" else "other"
            )
        elif match["punct"] in {"}", ")"} and scopes:
            scopes.pop()
        if name is not None and added[offset] and _spelling(name) in names:
            count += 1
        boundary = bool(match["type_body"] or match["table"] or match["punct"] in {";", ",", "{"})
    return count


def mirrored_state_count(patch: str, state_source_fields: Iterable[str]) -> int:
    """Return a lower bound on added declarations matching inventory state fields.

    Report this measure as "mirrored-state count (lower bound)". It can miss
    members whose enclosing declaration is outside the retained hunk context
    and members of intersection type literals such as ``A & { ... }``.
    An exhaustive measure would require base declaration ranges as a pure
    input; this patch-only API does not claim an exhaustive count.

    Parse each hunk's candidate text together so multiline type headers, nested
    types, strings and block comments preserve their scope. Context establishes
    scope but only declaration names on added lines contribute to the count.
    """
    names = {_spelling(name) for name in state_source_fields}
    count = 0
    source: list[str] = []
    added: list[bool] = []
    for line in patch.splitlines():
        if line.startswith(("@@", "diff --git", "+++")):
            count += _count_declarations("".join(source), added, names)
            source.clear()
            added.clear()
        elif line.startswith(("+", " ")):
            text = line[1:] + "\n"
            source.append(text)
            added.extend([line.startswith("+")] * len(text))
    return count + _count_declarations("".join(source), added, names)
