"""Pure holder discovery and miss mechanism measures."""

import re
from typing import Literal

from code_extension.fact_shapes.attempts import Attempt, HolderSpec
from code_extension.fact_shapes.outcome import FactOutcome, Missed


def normalized(text: str) -> str:
    return " ".join(text.split())


def holder_seen(attempt: Attempt, holder: HolderSpec) -> bool:
    for call in attempt.calls:
        if call.name == "submit_output" and call.returned_text == "submitted":
            break
        if (
            call.name in {"read_file", "run_command"}
            and holder.fact_lines
            and all(
                normalized(line) in normalized(call.returned_text or "")
                for line in holder.fact_lines
            )
        ):
            return True
    return False


def holder_opened_with_read_file(attempt: Attempt, holder: HolderSpec) -> bool:
    for call in attempt.calls:
        if call.name == "submit_output" and call.returned_text == "submitted":
            break
        if call.name == "read_file" and call.arguments is not None:
            path = call.arguments.get("path")
            if isinstance(path, str) and path.removeprefix("./") in holder.paths:
                return True
    return False


def changed_paths(patch: str) -> set[str]:
    return {
        path for side, path in re.findall(r"^(---|\+\+\+) [ab]/([^\t\n]+)", patch, re.MULTILINE)
    }


def miss_type(
    attempt: Attempt, holder: HolderSpec, outcome: FactOutcome
) -> Literal["touched_but_wrong", "read_not_changed", "never_touched"] | None:
    if not isinstance(outcome, Missed):
        return None
    if changed_paths(attempt.patch).intersection(holder.paths):
        return "touched_but_wrong"
    return "read_not_changed" if holder_seen(attempt, holder) else "never_touched"
