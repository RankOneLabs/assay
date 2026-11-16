"""Inventory-driven single-source checks over a materialized TypeScript tree.

This checker recognizes literal unions, arrays, enum constructors and SQL CHECK
lists. It also checks declared state fields and SQL columns. Imports and readers
are permitted: ownership concerns declarations, not references. SQL holders must
be explicitly named in the inventory; they never receive a blanket exemption.
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


def _without_comments(source: str) -> str:
    # Preserve quoted strings so comment-like text in a literal is not erased.
    token = re.compile(
        r"""("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|/\*.*?\*/|//[^\n]*|--[^\n]*""", re.S
    )
    return token.sub(lambda match: match.group(1) or "", source)


def _value_lists(source: str) -> list[frozenset[str]]:
    return [frozenset(re.findall(_LITERAL, match.group())) for match in _LIST.finditer(source)]


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


def audit(root: Path, inventory: Inventory) -> tuple[Finding, ...]:
    """Return ownership violations, with paths relative to any supplied root."""
    sources = {
        path.relative_to(root).as_posix(): _without_comments(path.read_text())
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix in {".ts", ".sql"}
    }
    findings: list[Finding] = []
    for concept in inventory.concepts:
        declaring = sources.get(concept.declaring_file, "")
        declaration = re.search(
            rf"\b(?:const|let|type|enum)\s+{re.escape(concept.symbol)}\b", declaring
        )
        if declaration is None or concept.members not in _value_lists(declaring):
            findings.append(Finding(concept.name, concept.declaring_file, "missing declaration"))
        allowed = {concept.declaring_file, *concept.outside_holders}
        for holder in concept.outside_holders:
            if concept.members not in _value_lists(sources.get(holder, "")):
                findings.append(Finding(concept.name, holder, "missing outside-code holder"))
        for path, source in sources.items():
            count = _value_lists(source).count(concept.members)
            if count > (1 if path in allowed else 0):
                findings.append(Finding(concept.name, path, "duplicate concept value declaration"))
    for state in inventory.states:
        if (
            _state_declarations(sources.get(state.source, ""), state.symbol, state.declaration_kind)
            != 1
        ):
            findings.append(Finding(state.name, state.source, "missing or repeated state source"))
        for path, source in sources.items():
            if path != state.source and any(
                _state_declarations(source, symbol, state.declaration_kind)
                for symbol in (state.symbol, *state.aliases)
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
