"""D18: read-only shell commands count as file inspections.

A model that inspects through ``run_command`` (``grep -rn Sym .``, ``sed -n
'1,40p' src/a.ts``) inspects as surely as one that calls ``search_files`` or
``read_file``. Each recognized command segment becomes the equivalent virtual
call at the position of the ``run_command`` that ran it, so every inspection
measure sees shell and tool inspections the same way.

Recognition is deliberately narrow and fails closed. ``grep``/``egrep``/
``fgrep``/``rg``/``git grep`` become searches. ``cat``/``head``/``tail``/
``nl``/``sed -n``/``awk`` with explicit file operands become reads. A segment
reading only from a pipe, a path with a glob or variable, ``sed -i``, and
anything else are not inspections. The command must have exited 0, or 1 for
a lone search segment, grep's "no match", which still inspected the scope.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Mapping
from typing import Any

WORKSPACE = "/workspace"
SEARCH_COMMANDS = frozenset({"grep", "egrep", "fgrep", "rg"})
READ_COMMANDS = frozenset({"cat", "head", "tail", "nl", "sed", "awk"})
# Options whose value is a separate argument, per command family.
GREP_VALUE_OPTIONS = frozenset({"-A", "-B", "-C", "-m", "-f", "--max-count", "--context",
                                "--after-context", "--before-context", "--include",
                                "--exclude", "--exclude-dir"})
RG_VALUE_OPTIONS = frozenset({"-A", "-B", "-C", "-m", "-g", "-t", "-T", "-f", "--glob",
                              "--type", "--type-not", "--max-count", "--context"})
READ_VALUE_OPTIONS = {"head": frozenset({"-n", "-c"}), "tail": frozenset({"-n", "-c"}),
                      "nl": frozenset({"-b", "-w", "-s", "-v", "-i"}),
                      "sed": frozenset({"-e", "-f"}), "awk": frozenset({"-F", "-v", "-f"})}
_OPERATORS = frozenset({";", "|", "||", "&", "&&", "(", ")", ";;", "|&"})
_UNSAFE_PATH = re.compile(r"[*?\[\]$`{}~]")


def _segments(command: str) -> list[list[str]]:
    """Quote-aware split on shell operators, with redirections removed.

    A command that does not tokenize yields no segments, so it is not an
    inspection. A redirection's target is never an operand, so ``cat > f``
    reads nothing and ``grep -rn X . 2>/dev/null`` keeps only its real operands.
    """
    lexer = shlex.shlex(command.replace("\n", ";"), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return []
    result: list[list[str]] = []
    current: list[str] = []
    skip_next = False
    for index, token in enumerate(tokens):
        if skip_next:
            skip_next = False
            continue
        if token in _OPERATORS:
            if current:
                result.append(current)
            current = []
            continue
        if token[0] in "<>" or token in (">&", "&>"):
            if current and current[-1].isdigit() and index > 0 and tokens[index - 1].isdigit():
                current.pop()
            skip_next = True
            continue
        current.append(token)
    if current:
        result.append(current)
    cleaned = []
    for segment in result:
        while segment and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", segment[0]):
            segment = segment[1:]
        if segment:
            cleaned.append(segment)
    return cleaned


def _repository_path(token: str, cwd: str) -> str | None:
    """A workspace-relative path, ``.`` for the root, or None when unsafe."""
    if not token or _UNSAFE_PATH.search(token):
        return None
    absolute = token if token.startswith("/") else f"{cwd.rstrip('/')}/{token}"
    parts: list[str] = []
    for part in absolute.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(part)
    root = WORKSPACE.strip("/").split("/")
    if parts[:len(root)] != root:
        return None
    relative = "/".join(parts[len(root):])
    return relative or "."


def _operands(tokens: list[str], value_options: frozenset[str]) -> tuple[list[str], list[str]]:
    """Separate option values from operands; ``-e`` patterns are returned too."""
    patterns: list[str] = []
    operands: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            operands.extend(tokens[index + 1:])
            break
        if token in ("-e", "--regexp"):
            if index + 1 < len(tokens):
                patterns.append(tokens[index + 1])
            index += 2
            continue
        if token.startswith("--regexp="):
            patterns.append(token.split("=", 1)[1])
        elif token in value_options:
            index += 2
            continue
        elif not token.startswith("-") or token == "-":
            operands.append(token)
        index += 1
    return patterns, operands


def _search(tokens: list[str], cwd: str) -> list[dict[str, Any]]:
    name = tokens[0]
    if name == "git":
        if len(tokens) < 2 or tokens[1] != "grep":
            return []
        name, tokens = "git grep", tokens[1:]
    rest = tokens[1:]
    value_options = RG_VALUE_OPTIONS if name == "rg" else GREP_VALUE_OPTIONS
    patterns, operands = _operands(rest, value_options)
    if not patterns:
        if not operands:
            return []
        patterns, operands = [operands[0]], operands[1:]
    recursive = name in ("rg", "git grep") or any(
        flag in ("-r", "-R", "--recursive", "--dereference-recursive")
        or (flag.startswith("-") and not flag.startswith("--") and ("r" in flag or "R" in flag))
        for flag in rest if flag.startswith("-"))
    if not operands:
        if not recursive:
            return []  # grep with no file reads its pipe, not the repository
        operands = ["."]
    searches = []
    for operand in operands:
        scope = _repository_path(operand, cwd)
        if scope is None:
            continue
        if not recursive and scope == ".":
            continue
        for pattern in patterns:
            searches.append({"name": "search_files", "exit_code": 0, "derived_from": "shell",
                             "arguments": {"query": pattern, "scope": scope}})
    return searches


def _read(tokens: list[str], cwd: str) -> list[dict[str, Any]]:
    name = tokens[0]
    rest = tokens[1:]
    quiet = any(t == "-n" or (t.startswith("-n") and len(t) > 2) for t in rest)
    in_place = any(t.startswith(("-i", "--in-place")) for t in rest)
    if name == "sed" and (not quiet or in_place):
        return []  # without -n sed prints the whole stream; -i edits it
    patterns, operands = _operands(rest, READ_VALUE_OPTIONS.get(name, frozenset()))
    if name in ("sed", "awk") and not patterns and operands:
        operands = operands[1:]  # the script
    reads = []
    for operand in operands:
        path = _repository_path(operand, cwd)
        if path is None or path == ".":
            continue
        reads.append({"name": "read_file", "exit_code": 0, "derived_from": "shell",
                      "arguments": {"path": path}})
    return reads


def shell_inspections(call: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Virtual search and read calls for one successful ``run_command``."""
    arguments = call.get("arguments")
    if call.get("name") != "run_command" or not isinstance(arguments, dict):
        return []
    command = arguments.get("command")
    if not isinstance(command, str):
        return []
    segments = _segments(command)
    exit_code = call.get("exit_code")
    lone_search = len(segments) == 1 and segments[0][0] in (*SEARCH_COMMANDS, "git")
    if not (exit_code == 0 or (exit_code == 1 and lone_search)):
        return []
    cwd = WORKSPACE
    derived: list[dict[str, Any]] = []
    for tokens in segments:
        head = tokens[0]
        if head == "cd":
            target = _repository_path(tokens[1], cwd) if len(tokens) > 1 else None
            if target is None:
                return derived  # left the workspace: later paths are not repository paths
            cwd = WORKSPACE if target == "." else f"{WORKSPACE}/{target}"
        elif head in SEARCH_COMMANDS or head == "git":
            derived.extend(_search(tokens, cwd))
        elif head in READ_COMMANDS:
            derived.extend(_read(tokens, cwd))
    return derived
