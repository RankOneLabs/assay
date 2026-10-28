"""Versions required for comparable metric output."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
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
TYPESCRIPT_PINS = {"tree-sitter-typescript": "0.23.2"}
NODE_PINS = {"jscpd": JSCPD, "dependency-cruiser": DEPENDENCY_CRUISER, "typescript": TYPESCRIPT}
_SOURCE_NODE_TOOLS = Path(__file__).resolve().parents[3] / "vendor" / "node-tools"
_BUNDLED_NODE_TOOLS = (
    _SOURCE_NODE_TOOLS
    if _SOURCE_NODE_TOOLS.is_dir()
    else Path(__file__).resolve().parents[1] / "vendor" / "node-tools"
)


def _user_node_tools() -> Path:
    if os.name == "nt":
        cache = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return cache / "assay" / "node-tools"


if "ASSAY_NODE_TOOLS" in os.environ:
    NODE_TOOLS = Path(os.environ["ASSAY_NODE_TOOLS"]).expanduser().resolve()
else:
    NODE_TOOLS = _SOURCE_NODE_TOOLS if _SOURCE_NODE_TOOLS.is_dir() else _user_node_tools()


def install_node_tools(*, offline: bool = False) -> Path:
    """Install the bundled lockfile's packages into the selected writable directory."""
    try:
        NODE_TOOLS.mkdir(parents=True, exist_ok=True)
        if NODE_TOOLS != _BUNDLED_NODE_TOOLS:
            for name in ("package.json", "package-lock.json"):
                shutil.copyfile(_BUNDLED_NODE_TOOLS / name, NODE_TOOLS / name)
    except OSError as error:
        raise ToolUnavailable("node-tools", f"cannot prepare {NODE_TOOLS}: {error}") from error
    npm_ci(NODE_TOOLS, offline=offline)
    assert_pinned_tools()
    return NODE_TOOLS


def npm_ci(directory: Path, *, offline: bool, include_dev: bool = False) -> None:
    """Install exactly the lockfile in *directory*, running no package scripts."""
    npm = shutil.which("npm")
    if npm is None:
        raise ToolUnavailable("npm", "npm executable was not found")
    command = [npm, "ci", "--ignore-scripts", "--no-audit", "--no-fund"]
    if include_dev:
        # A project's compiler and types are usually devDependencies, which an
        # inherited omit=dev or NODE_ENV=production would otherwise drop.
        command.append("--include=dev")
    if offline:
        command.append("--offline")
    try:
        subprocess.run(command, cwd=directory, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError) as error:
        detail = (
            (error.stderr or str(error)).strip()
            if isinstance(error, subprocess.CalledProcessError)
            else str(error)
        )
        raise ToolUnavailable("npm", f"npm ci failed in {directory}: {detail}") from error


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
    bin_dir = NODE_TOOLS / "node_modules" / ".bin"
    binary = bin_dir / f"{name}.cmd"
    if not binary.is_file():
        binary = bin_dir / name
    if not binary.is_file():
        raise ToolUnavailable(name, "run assay code-metrics install-node-tools")
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
    for tool, expected in (PINS | RUST_PINS | TYPESCRIPT_PINS).items():
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
