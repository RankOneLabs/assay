"""Public measurement API."""
from __future__ import annotations

import statistics
from difflib import SequenceMatcher

from .models import DELTAS, Snapshot, _Config
from .pins import assert_pinned_tools
from .tools import _python, _snapshot


def measure(
    before: Snapshot,
    after: Snapshot,
    *,
    clone_min_lines: int = 5,
    clone_min_tokens: int = 50,
    ruff_ignore: tuple[str, ...] = (),
) -> dict[str, float | None]:
    """after - before for every repository metric, plus new-code metrics for the change."""
    assert_pinned_tools()
    config = _Config(clone_min_lines, clone_min_tokens, ruff_ignore)
    old, new = _snapshot(before, config), _snapshot(after, config)
    result: dict[str, float | None] = {}
    for key in DELTAS:
        if key == "radon.mi":
            shared = sorted(set(old["mi"]) & set(new["mi"]))
            result[key] = (
                round(statistics.fmean(new["mi"][p] - old["mi"][p] for p in shared), 3)
                if shared
                else 0.0
            )
        elif old[key] is None or new[key] is None:
            result[key] = None
        else:
            result[key] = round(new[key] - old[key], 3)
    added = _added_lines(before, after)
    result["new_lines"] = sum(len(lines) for lines in added.values())
    result["new_duplicated_lines"] = sum(
        len(lines & new["cloned_lines"].get(path, set())) for path, lines in added.items()
    )
    result["new_max_nesting_depth"] = max(
        (
            depth
            for path, start, end, depth in new["functions"]
            if any(start <= line <= end for line in added.get(path, ()))
        ),
        default=0,
    )
    return result


def _added_lines(before: Snapshot, after: Snapshot) -> dict[str, set[int]]:
    """1-based line numbers of non-blank lines in ``after`` that ``before`` lacks."""
    added: dict[str, set[int]] = {}
    for path, text in _python(after).items():
        new = text.splitlines()
        old = before.get(path, "").splitlines()
        lines: set[int] = set()
        for tag, _, _, start, end in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
            if tag in ("insert", "replace"):
                lines.update(n + 1 for n in range(start, end) if new[n].strip())
        if lines:
            added[path] = lines
    return added
