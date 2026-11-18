"""Pure intent-text lint and verbatim fact-title alignment checks."""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from code_extension.fact_shapes.cells import CELLS

# Exact, case-sensitive matches only; these words describe the requested feature.
ALLOWLIST: dict[str, str] = {
    "triaged": "Ordinary user-facing workflow stage requested by the issue.",
    "attestation": "Ordinary user-facing evidence category requested by the issue.",
    "stage": "Ordinary workflow noun required to describe the feature.",
    "operations": "Ordinary plural noun describing public service behavior.",
    "length": "Ordinary measurement word describing record label limits.",
}


@dataclass(frozen=True)
class Finding:
    token: str
    source: str


def forbidden_tokens(holders: Path, base: Path) -> dict[str, tuple[str, ...]]:
    """Collect provenance without requiring a loaded or qualified scenario."""
    result: dict[str, set[str]] = {}

    def add(token: str, source: str) -> None:
        if token:
            result.setdefault(token, set()).add(source)

    for cell in CELLS:
        # The type is a required place in every arm, though no cell manipulates it.
        for path in (cell.edit_site, f"{cell.feature}/types.ts", *cell.holders):
            add(path, "cells.py:path")
            add(Path(path).name, "cells.py:basename")
    specs = json.loads(holders.read_text(encoding="utf-8"))
    for spec in specs:
        for role in ("manipulated", "anchor"):
            fact = spec[role]
            for path in fact["holder_paths"]:
                add(path, "holders.json:path")
                add(Path(path).name, "holders.json:basename")
            for lines in fact["fact_lines"].values():
                for line in lines:
                    for literal in re.findall(r"""["']([^"']+)["']""", line):
                        add(literal, "holders.json:key literal")
                    for identifier in re.findall(
                        r"\b[A-Za-z_$][\w$]*\b",
                        re.sub(
                            r"/(?:\\.|[^/\n])+/[a-z]*", "", re.sub(r"""["'][^"']*["']""", "", line)
                        ),
                    ):
                        if identifier not in {"export", "const", "as", "if", "throw", "new"}:
                            add(identifier, "holders.json:identifier")
    for export_path in sorted(base.rglob("*.ts")):
        text = export_path.read_text(encoding="utf-8")
        for identifier in re.findall(
            r"\bexport\s+(?:declare\s+)?(?:async\s+)?(?:function|class|const|let|var|type|interface|enum)\s+([\w$]+)",
            text,
        ):
            add(identifier, f"base export:{export_path.relative_to(base)}")
        for clause in re.findall(r"\bexport\s*(?:type\s*)?\{([^}]+)\}", text):
            for entry in clause.split(","):
                names = entry.strip().split()
                if names:
                    add(names[-1], f"base export:{export_path.relative_to(base)}")
    return {token: tuple(sorted(sources)) for token, sources in sorted(result.items())}


def lint(text: str, forbidden: Mapping[str, tuple[str, ...]]) -> tuple[Finding, ...]:
    """Report each named token once, preferring a path over overlapping basenames."""
    candidates: list[tuple[int, int, str]] = []
    for token in forbidden:
        if not token or token in ALLOWLIST:
            continue
        pattern = r"(?<![\w$])" + re.escape(token) + r"(?![\w$])"
        candidates.extend(
            (match.start(), match.end(), token) for match in re.finditer(pattern, text)
        )
    occupied: list[tuple[int, int]] = []
    matched: set[str] = set()
    for start, end, token in sorted(
        candidates, key=lambda item: (item[0] - item[1], item[0], item[2])
    ):
        if any(start < stop and end > begin for begin, stop in occupied):
            continue
        occupied.append((start, end))
        matched.add(token)
    return tuple(Finding(token, "; ".join(forbidden[token])) for token in sorted(matched))


def fact_titles(source: str) -> tuple[str, ...]:
    return tuple(re.findall(r"""\b(?:test|it)\(\s*["'](fact:[^"'\n]+)["']""", source))


def parse_map(markdown: str) -> dict[tuple[str, str], str]:
    """Read scenario | title | exact sentence rows from the study table."""
    rows: dict[tuple[str, str], str] = {}
    for line in markdown.splitlines():
        parts = [part.strip() for part in line.strip().strip("|").split("|")]
        if len(parts) == 3 and parts[1].startswith("fact:"):
            key = (parts[0], parts[1])
            if key in rows:
                raise ValueError(f"duplicate alignment row: {key}")
            rows[key] = parts[2]
    return rows


def check_alignment(
    scenario: str, task: str, titles: tuple[str, ...], markdown: str
) -> tuple[str, ...]:
    rows = parse_map(markdown)
    return tuple(
        title
        for title in titles
        if not rows.get((scenario, title)) or rows[scenario, title] not in task
    )
