"""Deterministic observations from one sealed verification-pilot trajectory."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from verification_pilot.ground_truth import Remnant
from verification_pilot.migrations import Migration, OwnershipGroup


def calls(turn: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [call for call in turn.get("tool_calls", ()) if isinstance(call, dict)]


def successful(call: Mapping[str, Any]) -> bool:
    return call.get("exit_code") == 0


def scope_contains(scope: str, path: str) -> bool:
    scope = scope.removeprefix("./").rstrip("/")
    return scope in ("", ".") or path == scope or path.startswith(scope + "/")


def inspected_path(turn: Mapping[str, Any], path: str) -> bool:
    for call in calls(turn):
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
    return any(
        owner == group and inspected_path(turn, path)
        for path, owner in migration.ownership_groups.items()
    )


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


def ran_tests(turn: Mapping[str, Any]) -> bool:
    return any(
        call.get("name") == "run_command"
        and successful(call)
        and isinstance(call.get("arguments"), dict)
        and bool(re.search(r"(?:^|\s)(?:bun|npm|npx|pnpm|yarn)\s+(?:run\s+)?test\b",
                           str(call["arguments"].get("command", ""))))
        for call in calls(turn)
    )


def changed_paths(diff: str | None) -> set[str]:
    if diff is None:
        return set()
    return set(re.findall(r"^\+\+\+ b/(.+)$", diff, flags=re.MULTILINE))


def changed_line(diff: str | None, path: str, line: int) -> bool:
    """The diff hunk, rather than a symbol mention elsewhere, covers this source line."""
    if diff is None:
        return False
    current: str | None = None
    old_line = 0
    for text in diff.splitlines():
        if text.startswith("+++ b/"):
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
    old_token = re.compile(
        rf"(?<![A-Za-z0-9_]){re.escape(remnant.location.symbol)}(?![A-Za-z0-9_])"
    )
    current: str | None = None
    old_line = 0
    removed = False
    added = False
    for text in diff.splitlines():
        if text.startswith("+++ b/"):
            current = text[6:]
        elif text.startswith("@@ "):
            match = re.search(r"@@ -(\d+)", text)
            if match:
                old_line = int(match.group(1))
        elif text.startswith("-") and not text.startswith("---"):
            if current == remnant.location.path and old_line == remnant.location.line:
                removed = bool(old_token.search(text[1:]))
            old_line += 1
        elif text.startswith("+") and not text.startswith("+++"):
            if current == remnant.location.path and old_token.search(text[1:]):
                added = True
        elif text.startswith(" "):
            old_line += 1
    return removed and not added
