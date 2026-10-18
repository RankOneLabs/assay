"""Verify the self-trust fixture in the pinned sandbox image.

For each concept this runs `tsc --noEmit` and `bun test` on the clean
control, on each of the three planted subjects, and on a blind replace-all
of a planted subject. The fixture holds only if:

- the clean control and every planted subject pass both checks;
- no planted subject spells the old type name outside the historical notes,
  so a whole-word search for it finds nothing;
- the blind replace-all fails `bun test`, through the compatibility test.

Run ``uv run python -m verification_pilot.self_trust.check --image <digest>
--work ~/.assay-vp/self-trust-check`` from ``experiments/``; the result is
written to ``raw/self_trust/fixture-check.json``. Docker Desktop cannot
bind-mount ``/tmp``, so ``--work`` must live elsewhere.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from assay.investigations.workflow_correctness import workflow_tree_digest
from verification_pilot.fixtures import GROUPS, read_raw_repository, whole_word_pattern
from verification_pilot.self_trust.concepts import (
    CONCEPTS,
    HISTORICAL,
    Concept,
    blind_replace,
    subject_repository,
)

RESULT = Path(__file__).resolve().parents[1] / "raw" / "self_trust" / "fixture-check.json"
_SCRIPT = """
for case in /work/cases/*; do
  cd "$case"
  tsc --noEmit -p tsconfig.json > /dev/null 2>&1; t=$?
  bun test > /dev/null 2>&1; b=$?
  echo "$(basename "$case") $t $b"
done
"""


def cases(repository: Mapping[str, str], concept: Concept) -> dict[str, dict[str, str]]:
    planted = {group: subject_repository(repository, concept, group) for group in GROUPS}
    return {
        f"{concept.name}-clean": subject_repository(repository, concept, None),
        **{f"{concept.name}-{group}": tree for group, tree in planted.items()},
        f"{concept.name}-blind": blind_replace(planted["group_a"], concept),
    }


def _write(root: Path, tree: Mapping[str, str]) -> None:
    for path, source in tree.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")


def _old_type_hits(tree: Mapping[str, str], concept: Concept) -> list[str]:
    pattern = whole_word_pattern(concept.old_type)
    return sorted(path for path, source in tree.items()
                  if path not in HISTORICAL and pattern.search(source))


def run_check(image: str, work: Path) -> dict[str, Any]:
    repository = read_raw_repository()
    if work.exists():
        shutil.rmtree(work)
    trees: dict[str, tuple[Concept, dict[str, str]]] = {}
    for concept in CONCEPTS:
        for name, tree in cases(repository, concept).items():
            _write(work / "cases" / name, tree)
            trees[name] = (concept, tree)
    completed = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "-v", f"{work}:/work",
         "--entrypoint", "sh", image, "-c", _SCRIPT],
        capture_output=True, text=True, timeout=1800, check=True,
    )
    exits = {name: (int(tsc), int(bun)) for name, tsc, bun in
             (line.split() for line in completed.stdout.splitlines() if line.strip())}
    results: dict[str, Any] = {}
    for name, (concept, tree) in sorted(trees.items()):
        tsc, bun = exits[name]
        kind = name.rsplit("-", 1)[1]
        entry = {"tree_digest": workflow_tree_digest(tree), "tsc_exit": tsc, "bun_test_exit": bun,
                 "old_type_hits": _old_type_hits(tree, concept)}
        entry["holds"] = (bun != 0 if kind == "blind"
                          else tsc == 0 and bun == 0 and not entry["old_type_hits"])
        results[name] = entry
    return {"image": image, "cases": results, "holds": all(e["holds"] for e in results.values())}


REFACTOR_RESULT = RESULT.parent / "refactor-check.json"
REWRITE_RESULT = RESULT.parent / "rewrite-check.json"


def run_refactor_check(image: str, rung_name: str = "refactor") -> dict[str, Any]:
    """The refactor's start and four subject trees, through the evaluator's own checks.

    Every tree must typecheck and pass the visible tests. The start and the
    clean refactor pass every hidden test; each omission fails its own share's
    hidden test and no other.
    """
    from verification_pilot.self_trust.ladder import RUNGS
    from verification_pilot.self_trust.refactor_evaluation import run_checks

    rung = RUNGS[rung_name]
    trees = {"start": rung.start_tree(), "clean": rung.subject_tree(None),
             **{f"omit-{group}": rung.subject_tree(group) for group in rung.order}}
    results: dict[str, Any] = {}
    for name, tree in trees.items():
        checks = run_checks(tree, image, rung)
        omitted = name.removeprefix("omit-") if name.startswith("omit-") else None
        if name == "start" and rung.name != "refactor":
            # A rewrite's hidden tests use the API the rewrite creates, so at its
            # start they cannot compile; only the visible suite must hold there.
            holds = checks["visible"] == 0
        else:
            holds = (checks["tsc"] == 0 and checks["visible"] == 0
                     and all(passed == (group != omitted)
                             for group, passed in checks["hidden"].items()))
        results[name] = {"tree_digest": workflow_tree_digest(tree), **checks, "holds": holds}
    return {"image": image, "cases": results, "holds": all(e["holds"] for e in results.values())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--fixture", default="rename",
                        choices=("rename", "refactor", "refactor-long", "rewrite0", "rewrite0-read",
                                 "rewrite1",
                                 "rewrite2", "rewrite"))
    args = parser.parse_args()
    if args.fixture != "rename":
        refactor = run_refactor_check(args.image, args.fixture)
        target = RESULT.parent / f"{args.fixture}-check.json"
        target.write_text(json.dumps(refactor, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")
        print(json.dumps({"holds": refactor["holds"]}))
        return
    result = run_check(args.image, args.work.expanduser().resolve())
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"holds": result["holds"],
                      "failed": [n for n, e in result["cases"].items() if not e["holds"]]}))


if __name__ == "__main__":
    main()
