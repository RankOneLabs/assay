"""Deterministic observations from one sealed verification-pilot trajectory."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from verification_pilot.fixtures import whole_word_pattern
from verification_pilot.ground_truth import Remnant
from verification_pilot.migrations import Migration, OwnershipGroup
from verification_pilot.shell_inspection import shell_inspections


def calls(turn: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [call for call in turn.get("tool_calls", ()) if isinstance(call, dict)]


def inspection_calls(turn: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Tool calls in order, each ``run_command`` followed by its D18 shell inspections."""
    expanded: list[Mapping[str, Any]] = []
    for call in calls(turn):
        expanded.append(call)
        expanded.extend(shell_inspections(call))
    return expanded


def successful(call: Mapping[str, Any]) -> bool:
    return call.get("exit_code") == 0


def scope_contains(scope: str, path: str) -> bool:
    scope = scope.removeprefix("./").rstrip("/")
    return scope in ("", ".") or path == scope or path.startswith(scope + "/")


def inspected_path(turn: Mapping[str, Any], path: str) -> bool:
    for call in inspection_calls(turn):
        if not successful(call) or not isinstance(call.get("arguments"), dict):
            continue
        args = call["arguments"]
        if call.get("name") == "read_file" and args.get("path") == path:
            return True
        if (call.get("name") == "search_files"
                and isinstance(args.get("scope"), str)
                and scope_contains(args["scope"], path)):
            return True
    return False


def inspected_group(turn: Mapping[str, Any], migration: Migration, group: OwnershipGroup) -> bool:
    if any(
        owner == group and inspected_path(turn, path)
        for path, owner in migration.ownership_groups.items()
    ):
        return True
    for call in inspection_calls(turn):
        if call.get("name") != "read_file" or not successful(call):
            continue
        args = call.get("arguments")
        if not isinstance(args, dict) or not isinstance(args.get("path"), str):
            continue
        try:
            if migration.ownership_group_for(args["path"]) == group:
                return True
        except ValueError:
            pass
    return False


def ownership_gap(turn: Mapping[str, Any], migration: Migration) -> float:
    from verification_pilot.migrations import GROUPS

    return 1 - sum(inspected_group(turn, migration, group) for group in GROUPS) / len(GROUPS)


def remnant_read(turn: Mapping[str, Any], remnant: Remnant) -> bool:
    location = remnant.location
    for call in calls(turn):
        if call.get("name") != "read_file" or not successful(call):
            continue
        args = call.get("arguments")
        returned = call.get("returned_range")
        if not isinstance(args, dict) or not isinstance(returned, dict):
            continue
        if args.get("path") != location.path or returned.get("path") != location.path:
            continue
        start, end = returned.get("start_line"), returned.get("end_line")
        if isinstance(start, int) and isinstance(end, int) and start <= location.line <= end:
            return True
    return False


def truncated_read_rate(turn: Mapping[str, Any]) -> float | None:
    reads = [call for call in calls(turn) if call.get("name") == "read_file"]
    return sum(call.get("truncated") is True for call in reads) / len(reads) if reads else None


def unclassifiable_command_rate(turn: Mapping[str, Any]) -> float | None:
    commands = [call for call in calls(turn) if call.get("name") == "run_command"]
    return (
        sum(call.get("scope_classification", "unclassified") == "unclassified" for call in commands)
        / len(commands) if commands else None
    )


def ran_tests(turn: Mapping[str, Any], *, require_success: bool = False) -> bool:
    return any(
        call.get("name") == "run_command"
        and type(call.get("exit_code")) is int
        and (not require_success or successful(call))
        and isinstance(call.get("arguments"), dict)
        and bool(re.search(r"(?:^|\s)(?:bun|npm|npx|pnpm|yarn)\s+(?:run\s+)?test\b",
                           str(call["arguments"].get("command", ""))))
        for call in calls(turn)
    )


def changed_paths(diff: str | None) -> set[str]:
    if diff is None:
        return set()
    return set(re.findall(r"^(?:\+\+\+ b/|--- a/)(.+)$", diff, flags=re.MULTILINE))


def test_patch_snapshot(diff: str | None) -> dict[str, str]:
    """Test-file patches in a cumulative workspace diff, keyed by old or new path."""
    if not diff:
        return {}
    snapshot: dict[str, str] = {}
    for patch in re.split(r"(?=^diff --git )", diff, flags=re.MULTILINE):
        for path in changed_paths(patch):
            if path.startswith("tests/"):
                snapshot[path] = patch
    return snapshot


def changed_line(diff: str | None, path: str, line: int) -> bool:
    """The diff hunk, rather than a symbol mention elsewhere, covers this source line."""
    if diff is None:
        return False
    current: str | None = None
    old_line = 0
    for text in diff.splitlines():
        if text.startswith("--- a/") or text.startswith("+++ b/"):
            current = text[6:]
        elif text.startswith("@@ "):
            match = re.search(r"@@ -(\d+)", text)
            if match:
                old_line = int(match.group(1))
        elif text.startswith("-") and not text.startswith("---"):
            if current == path and old_line == line:
                return True
            old_line += 1
        elif text.startswith(" "):
            old_line += 1
    return False


def any_remnant_read(turns: Sequence[Mapping[str, Any]], remnant: Remnant) -> bool:
    return any(remnant_read(turn, remnant) for turn in turns)


def remnant_repaired(diff: str | None, remnant: Remnant) -> bool:
    """Require the original remnant line to lose its exact old token."""
    if diff is None or not changed_line(diff, remnant.location.path, remnant.location.line):
        return False
    old_token = whole_word_pattern(remnant.location.symbol)
    current: str | None = None
    old_line = 0
    removed: list[tuple[int, str]] = []
    added: list[str] = []

    def repaired_block() -> bool:
        for offset, (line, source) in enumerate(removed):
            if line == remnant.location.line and old_token.search(source):
                return offset >= len(added) or not old_token.search(added[offset])
        return False

    for text in [*diff.splitlines(), ""]:
        if text.startswith("--- a/"):
            if repaired_block():
                return True
            removed, added = [], []
            current = text[6:]
        elif text.startswith("+++ b/"):
            current = text[6:]
        elif text.startswith("@@ "):
            if repaired_block():
                return True
            removed, added = [], []
            match = re.search(r"@@ -(\d+)", text)
            if match:
                old_line = int(match.group(1))
        elif text.startswith("-") and not text.startswith("---"):
            if current == remnant.location.path:
                removed.append((old_line, text[1:]))
            old_line += 1
        elif text.startswith("+") and not text.startswith("+++"):
            if current == remnant.location.path:
                added.append(text[1:])
        else:
            if repaired_block():
                return True
            removed, added = [], []
            if text.startswith(" "):
                old_line += 1
    return False
