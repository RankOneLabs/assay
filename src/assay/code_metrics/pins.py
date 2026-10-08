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


def tool_versions() -> dict[str, str]:
    """Versions behind every number, for the run record."""
    return {name: version(name) for name in PINS} | {"jscpd": JSCPD.split("@")[1]}


def typescript_tool_versions() -> dict[str, str]:
    """Versions behind a TypeScript graph, recorded only when one was extracted."""
    return dict(package.rsplit("@", 1) for package in (DEPENDENCY_CRUISER, TYPESCRIPT))


def assert_pinned_tools() -> None:
    for tool, expected in PINS.items():
        resolved = version(tool)
        if resolved != expected:
            raise ToolVersionMismatch(tool, expected, resolved)
