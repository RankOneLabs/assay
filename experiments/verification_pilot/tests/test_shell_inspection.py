"""D18: read-only shell commands become the equivalent inspection calls."""

from typing import Any

import pytest

from verification_pilot.metrics import inspected_path, inspection_calls
from verification_pilot.shell_inspection import shell_inspections


def _run(command: str, exit_code: int = 0) -> dict[str, Any]:
    return {"name": "run_command", "arguments": {"command": command}, "exit_code": exit_code}


def _derived(command: str, exit_code: int = 0) -> list[tuple[str, dict[str, str]]]:
    derived = shell_inspections(_run(command, exit_code))
    return [(call["name"], call["arguments"]) for call in derived]


@pytest.mark.parametrize(("command", "expected"), [
    ('cd /workspace; git status --short | head; grep -rn "WorkOrderId" . --exclude-dir=x',
     [("search_files", {"query": "WorkOrderId", "scope": "."})]),
    ('grep -n "StageInstanceId\\|StageRunId" src/compiler/resolve-execution.ts',
     [("search_files", {"query": "StageInstanceId\\|StageRunId",
                        "scope": "src/compiler/resolve-execution.ts"})]),
    ("grep -rn Foo . 2>/dev/null | head -20", [("search_files", {"query": "Foo", "scope": "."})]),
    ("git grep -n WorkOrderId", [("search_files", {"query": "WorkOrderId", "scope": "."})]),
    ("rg -e WorkOrderId src", [("search_files", {"query": "WorkOrderId", "scope": "src"})]),
    ("sed -n '1,40p' src/a.ts", [("read_file", {"path": "src/a.ts"})]),
    ("cd src && head -n 20 a.ts ../tests/b.ts",
     [("read_file", {"path": "src/a.ts"}), ("read_file", {"path": "tests/b.ts"})]),
    ("cat /workspace/docs/migration.md", [("read_file", {"path": "docs/migration.md"})]),
])
def test_recognized_inspections(command: str, expected: list[Any]) -> None:
    assert _derived(command) == expected


@pytest.mark.parametrize("command", [
    "sed -i '15s/A/B/' src/a.ts",      # an edit, not a read
    "cat src/*.ts",                     # a glob the trace cannot resolve
    "cat > src/x.ts <<EOF",             # a write
    "cd /tmp && cat a.ts",              # outside the workspace
    "ls src | grep ts",                 # grep over a pipe, not the repository
    "grep Foo .",                       # non-recursive grep of a directory
    "cat ../../etc/passwd",             # escapes the workspace
    "echo 'unterminated",               # does not tokenize
])
def test_unrecognized_commands_are_not_inspections(command: str) -> None:
    assert _derived(command) == []


def test_exit_status_gates_shell_inspections() -> None:
    assert _derived("grep -rn Foo .", exit_code=1) == [
        ("search_files", {"query": "Foo", "scope": "."})]
    assert _derived("grep -rn Foo . ; cat src/a.ts", exit_code=1) == []
    assert _derived("cat src/a.ts", exit_code=2) == []


def test_shell_inspections_sit_where_their_command_ran() -> None:
    turn = {"tool_calls": [
        {"name": "write_file", "arguments": {"path": "src/a.ts"}, "exit_code": 0},
        _run("cat src/a.ts"),
    ]}
    names = [call["name"] for call in inspection_calls(turn)]
    assert names == ["write_file", "run_command", "read_file"]
    assert inspected_path(turn, "src/a.ts")
    assert not inspected_path(turn, "src/b.ts")
