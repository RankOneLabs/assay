"""Versions required for comparable metric output."""
from __future__ import annotations

from importlib.metadata import version

from .errors import ToolVersionMismatch

JSCPD = "jscpd@5.4.0"
DEPENDENCY_CRUISER = "dependency-cruiser@18.4.0"
# dependency-cruiser parses TypeScript with whichever compiler sits beside it.
TYPESCRIPT = "typescript@6.0.3"
PINS = {
    "radon": "6.0.1",
    "complexipy": "8.0.1",
    "lizard": "1.24.0",
    "grimp": "3.17",
    "ruff": "0.16.8",
    "mypy": "2.3.1",
}
# Pinned like PINS, but recorded in a report only when a Rust graph was extracted.
RUST_PINS = {
    "tree-sitter": "0.25.2",
    "tree-sitter-rust": "0.24.2",
}


def tool_versions() -> dict[str, str]:
    """Versions behind every number, for the run record."""
    return {name: version(name) for name in PINS} | {"jscpd": JSCPD.split("@")[1]}


def typescript_tool_versions() -> dict[str, str]:
    """Versions behind a TypeScript graph, recorded only when one was extracted."""
    return dict(package.rsplit("@", 1) for package in (DEPENDENCY_CRUISER, TYPESCRIPT))


def rust_tool_versions() -> dict[str, str]:
    """Versions behind a Rust graph, recorded only when one was extracted."""
    return {name: version(name) for name in RUST_PINS}


def assert_pinned_tools() -> None:
    for tool, expected in (PINS | RUST_PINS).items():
        resolved = version(tool)
        if resolved != expected:
            raise ToolVersionMismatch(tool, expected, resolved)
