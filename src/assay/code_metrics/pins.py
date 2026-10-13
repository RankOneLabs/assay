"""Versions required for comparable metric output."""

from __future__ import annotations

import json
from importlib.metadata import version
from pathlib import Path

from .errors import ToolUnavailable, ToolVersionMismatch

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
NODE_PINS = {"jscpd": JSCPD, "dependency-cruiser": DEPENDENCY_CRUISER, "typescript": TYPESCRIPT}
_SOURCE_NODE_TOOLS = Path(__file__).resolve().parents[3] / "vendor" / "node-tools"
NODE_TOOLS = (
    _SOURCE_NODE_TOOLS
    if _SOURCE_NODE_TOOLS.is_dir()
    else Path(__file__).resolve().parents[1] / "vendor" / "node-tools"
)


def node_tool_versions() -> dict[str, str]:
    """Resolved direct dependency versions from the committed npm lockfile."""
    lock = NODE_TOOLS / "package-lock.json"
    try:
        packages = json.loads(lock.read_text(encoding="utf-8"))["packages"]
        return {name: str(packages[f"node_modules/{name}"]["version"]) for name in NODE_PINS}
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ToolUnavailable("node-tools", f"unreadable lockfile {lock}: {error}") from error


def node_binary(name: str) -> str:
    """Use the installed tree selected by the committed lockfile, without npm execution."""
    binary = NODE_TOOLS / "node_modules" / ".bin" / name
    if not binary.is_file():
        raise ToolUnavailable(name, f"run npm ci --offline in {NODE_TOOLS}")
    return str(binary)


def tool_versions() -> dict[str, str]:
    """Versions behind every number, for the run record."""
    return {name: version(name) for name in PINS} | {"jscpd": node_tool_versions()["jscpd"]}


def typescript_tool_versions() -> dict[str, str]:
    """Versions behind a TypeScript graph, recorded only when one was extracted."""
    resolved = node_tool_versions()
    return {name: resolved[name] for name in ("dependency-cruiser", "typescript")}


def rust_tool_versions() -> dict[str, str]:
    """Versions behind a Rust graph, recorded only when one was extracted."""
    return {name: version(name) for name in RUST_PINS}


def assert_pinned_tools() -> None:
    for tool, expected in (PINS | RUST_PINS).items():
        resolved = version(tool)
        if resolved != expected:
            raise ToolVersionMismatch(tool, expected, resolved)
    resolved_node = node_tool_versions()
    for tool, pin in NODE_PINS.items():
        expected = pin.rsplit("@", 1)[1]
        if resolved_node[tool] != expected:
            raise ToolVersionMismatch(tool, expected, resolved_node[tool])
        installed = NODE_TOOLS / "node_modules" / tool / "package.json"
        if installed.is_file():
            try:
                installed_version = str(
                    json.loads(installed.read_text(encoding="utf-8"))["version"]
                )
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise ToolUnavailable(
                    tool, f"unreadable installed metadata {installed}: {error}"
                ) from error
            if installed_version != expected:
                raise ToolVersionMismatch(tool, expected, installed_version)
