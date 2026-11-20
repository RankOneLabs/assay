"""Inventory-driven single-source checks over a materialized TypeScript tree.

This checker recognizes literal unions, arrays, enum constructors, SQL CHECK
lists, switch-block case labels and object/record keys. Concepts with candidate
holders require exactly one explicit declaration in the declaring file, plus at
most one independent copy, declared once, in one candidate holder: the arm's
manipulated holder. Any other copy is a duplicate. Imports and derived views are
readers, not declarations. Legacy inventories retain their form-specific exemptions.
Inventoried state fields and SQL tables must still have one canonical source.

A concept with a trait symbol (round 5, stages) also has implicit holders: code that
decides a per-value behavior without naming the values. Its candidate holders must
read the declared traits, and no file may encode the values another way: by their
position in the declared list, or as numeric codes in a SQL CASE. A version's
manipulated holder is exactly the set of files these checks report.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast


@dataclass(frozen=True)
class Concept:
    name: str
    declaring_file: str
    symbol: str
    members: frozenset[str]
    outside_holders: tuple[str, ...]
    switch_holders: tuple[str, ...] = ()
    candidate_holders: tuple[str, ...] = ()
    trait_symbol: str = ""
    types_module: str = ""


@dataclass(frozen=True)
class State:
    name: str
    source: str
    symbol: str
    aliases: tuple[str, ...] = ()
    declaration_kind: str = "field"


@dataclass(frozen=True)
class Inventory:
    concepts: tuple[Concept, ...]
    states: tuple[State, ...]


@dataclass(frozen=True)
class Finding:
    name: str
    path: str
    message: str


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("inventory requires a string")
    return value


def _objects(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError("inventory requires a list")
    result: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("inventory requires objects")
        result.append(cast("dict[str, object]", item))
    return result


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError("inventory requires a list of strings")
    return tuple(_text(item) for item in value)


def load_inventory(path: Path) -> Inventory:
    data = cast("dict[str, object]", json.loads(path.read_text()))
    concepts = tuple(
        Concept(
            name=_text(item["name"]),
            declaring_file=_text(item["declaring_file"]),
            symbol=_text(item["symbol"]),
            members=frozenset(_strings(item["members"])),
            outside_holders=_strings(item.get("outside_holders", [])),
            switch_holders=_strings(item.get("switch_holders", [])),
            candidate_holders=_strings(item.get("candidate_holders", [])),
            trait_symbol=_text(item.get("trait_symbol", "")),
            types_module=_text(item.get("types_module", "")),
        )
        for item in _objects(data["concepts"])
    )
    states = tuple(
        State(
            _text(item["name"]),
            _text(item["source"]),
            _text(item["symbol"]),
            _strings(item.get("aliases", [])),
            _text(item.get("declaration_kind", "field")),
        )
        for item in _objects(data["states"])
    )
    names = [item.name for item in concepts] + [item.name for item in states]
    if len(set(names)) != len(names):
        raise ValueError("inventory names must be unique")
    return Inventory(concepts, states)


_LITERAL = r"""["']([^"'\n]*)["']"""
_LIST = re.compile(
    r"\[[^\[\]]*\]|\b(?:enum|IN)\s*\([^()]*\)|"
    r"""(?:["'][^"'\n]*["']\s*\|\s*)+["'][^"'\n]*["']""",
    re.IGNORECASE,
)

# Quoted text is opaque: braces and keywords inside it cannot delimit a switch.
_SWITCH_TOKEN = re.compile(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|\w+|[^\s]''')


def _switch_lists(source: str) -> list[frozenset[str]]:
    tokens = _SWITCH_TOKEN.findall(source)
    bodies: set[int] = set()
    for index, token in enumerate(tokens[:-1]):
        if token != "switch" or tokens[index + 1] != "(":
            continue
        depth = 0
        for cursor in range(index + 1, len(tokens)):
            if tokens[cursor] == "(":
                depth += 1
            elif tokens[cursor] == ")":
                depth -= 1
                if depth == 0:
                    if cursor + 1 < len(tokens) and tokens[cursor + 1] == "{":
                        bodies.add(cursor + 1)
                    break
    result: list[frozenset[str]] = []
    blocks: list[set[str] | None] = []
    for index, token in enumerate(tokens):
        if token == "{":
            blocks.append(set() if index in bodies else None)
        elif token == "}" and blocks:
            members = blocks.pop()
            if members is not None:
                result.append(frozenset(members))
        elif token == "case" and index + 2 < len(tokens) and tokens[index + 2] == ":":
            literal = re.fullmatch(_LITERAL, tokens[index + 1])
            if literal:
                for members in reversed(blocks):
                    if members is not None:
                        members.add(literal.group(1))
                        break
    return result


def _without_comments(source: str) -> str:
    # Preserve quoted strings so comment-like text in a literal is not erased.
    token = re.compile(
        r"""("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|/\*.*?\*/|//[^\n]*|--[^\n]*""", re.S
    )
    return token.sub(lambda match: match.group(1) or "", source)


def _value_lists(source: str) -> list[frozenset[str]]:
    return [frozenset(re.findall(_LITERAL, match.group())) for match in _LIST.finditer(source)]


def explicit_fact_count(source: str, members: frozenset[str]) -> int:
    """Count independent full enumerations, including object/record keys."""
    source = _without_comments(source)
    blocks: list[set[str]] = []
    objects = 0
    tokens = _SWITCH_TOKEN.findall(source)
    for index, token in enumerate(tokens):
        if token == "{":
            blocks.append(set())
        elif token == "}" and blocks:
            if blocks.pop() == members:
                objects += 1
        elif blocks and index + 1 < len(tokens) and tokens[index + 1] == ":":
            literal = re.fullmatch(_LITERAL, token)
            if literal and (index == 0 or tokens[index - 1] != "case"):
                blocks[-1].add(literal.group(1))
            elif re.fullmatch(r"[A-Za-z_$][\w$]*", token):
                blocks[-1].add(token)
    return _value_lists(source).count(members) + _switch_lists(source).count(members) + objects


def _state_declarations(source: str, symbol: str, kind: str = "field") -> int:
    if kind == "table":
        return len(
            re.findall(
                rf"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?{re.escape(symbol)}\s*\(",
                source,
                re.IGNORECASE,
            )
        )
    if kind != "field":
        raise ValueError(f"unknown state declaration kind: {kind}")
    # Camel and SQL snake spellings identify the same inventoried storage slot.
    snake = re.sub(r"(?<!^)([A-Z])", r"_\1", symbol).lower()
    names = "|".join(re.escape(name) for name in {symbol, snake})
    pattern = (
        rf"\b(?:{names})\s*(?:\??\s*:\s*[^;\n]+|=\s*new\b|"
        rf"\s+(?:BOOLEAN|INTEGER|TEXT)\b)"
    )
    return len(re.findall(pattern, source, re.IGNORECASE))


# A position in the declared value list, read through any import of it.
_POSITIONAL = re.compile(r"\b(?:values|stages)\s*\.\s*(?:indexOf|findIndex|at)\s*\(|"
                         r"\b(?:values|stages)\s*\[\s*\d+\s*\]")
_SQL_CODES = re.compile(r"\bCASE\s+\w*_code\b", re.IGNORECASE)


def _implicit_findings(concept: Concept, sources: dict[str, str]) -> list[Finding]:
    """Implicit holders: positional or coded decisions, and holders that skip the traits."""
    if not concept.trait_symbol:
        return []
    findings: list[Finding] = []
    for path, source in sources.items():
        if path == concept.declaring_file:
            continue
        folder, module = concept.types_module.rsplit("/", 1)
        reads_types = concept.types_module in source or (
            path.startswith(folder + "/") and f"./{module}" in source
        )
        if path.endswith(".ts") and reads_types and _POSITIONAL.search(source):
            findings.append(Finding(concept.name, path, "positional value encoding"))
        if path.endswith(".sql") and _SQL_CODES.search(source):
            findings.append(Finding(concept.name, path, "coded value encoding"))
    for path in concept.candidate_holders:
        holder = sources.get(path)
        if holder is None:
            findings.append(Finding(concept.name, path, "missing candidate holder"))
        elif path.endswith(".ts") and concept.trait_symbol not in holder:
            findings.append(Finding(concept.name, path, "holder does not read the declared traits"))
    return findings


def audit(root: Path, inventory: Inventory) -> tuple[Finding, ...]:
    """Return ownership violations, with paths relative to any supplied root."""
    sources = {
        path.relative_to(root).as_posix(): _without_comments(path.read_text())
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix in {".ts", ".sql"}
    }
    findings: list[Finding] = []
    for concept in inventory.concepts:
        if concept.candidate_holders:
            counts = {path: explicit_fact_count(source, concept.members)
                      for path, source in sources.items()}
            owners = [path for path, count in counts.items() if count]
            declared = counts.get(concept.declaring_file, 0)
            if not declared:
                findings.append(Finding(
                    concept.name, concept.declaring_file, "missing declaration"
                ))
            elif declared != (2 if concept.trait_symbol else 1):
                findings.append(Finding(
                    concept.name, concept.declaring_file, "duplicate concept value declaration"
                ))
            copies = [path for path in owners if path != concept.declaring_file]
            for path in copies:
                if (path not in concept.candidate_holders or counts[path] != 1
                        or len(copies) != 1):
                    findings.append(Finding(
                        concept.name, path, "duplicate concept value declaration"
                    ))
            if declared:
                declaration = re.search(
                    rf"\b(?:const|let|type)\s+{re.escape(concept.symbol)}\s*"
                    r"(?::\s*[^=;]+)?=\s*([^;]+)", sources[concept.declaring_file]
                )
                if declaration is None or not explicit_fact_count(
                    declaration.group(1), concept.members
                ):
                    findings.append(Finding(concept.name, concept.declaring_file,
                                            "missing declaration"))
            findings.extend(_implicit_findings(concept, sources))
            continue
        declaring = sources.get(concept.declaring_file, "")
        declaration = re.search(
            rf"\b(?:const|let|type)\s+{re.escape(concept.symbol)}\s*"
            r"(?::\s*[^=;]+)?=\s*([^;]+)", declaring
        )
        if declaration is None or concept.members not in _value_lists(declaration.group(1)):
            findings.append(Finding(concept.name, concept.declaring_file, "missing declaration"))
        allowed = {concept.declaring_file, *concept.outside_holders}
        for holder in concept.outside_holders:
            if concept.members not in _value_lists(sources.get(holder, "")):
                findings.append(Finding(concept.name, holder, "missing outside-code holder"))
        for holder in concept.switch_holders:
            if concept.members not in _switch_lists(sources.get(holder, "")):
                findings.append(Finding(concept.name, holder, "missing sanctioned switch holder"))
        for path, source in sources.items():
            count = _value_lists(source).count(concept.members)
            switches = _switch_lists(source).count(concept.members)
            if count > (1 if path in allowed else 0) or switches > (
                1 if path in concept.switch_holders else 0
            ):
                findings.append(Finding(concept.name, path, "duplicate concept value declaration"))
    for state in inventory.states:
        if (
            _state_declarations(sources.get(state.source, ""), state.symbol, state.declaration_kind)
            != 1
        ):
            findings.append(Finding(state.name, state.source, "missing or repeated state source"))
        for path, source in sources.items():
            if any(
                _state_declarations(source, symbol, state.declaration_kind)
                for symbol in (
                    state.aliases if path == state.source else (state.symbol, *state.aliases)
                )
            ):
                findings.append(Finding(state.name, path, "mirrored state field or column"))
    return tuple(findings)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("inventory", type=Path)
    args = parser.parse_args()
    findings = audit(args.root, load_inventory(args.inventory))
    for finding in findings:
        print(f"{finding.name}: {finding.path}: {finding.message}")
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
