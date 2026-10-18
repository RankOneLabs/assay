"""Record each share's work log by executing its plan in the sandbox image.

Each log runs alone, on a fresh copy of the start tree, through the bridge's
own tool layer, so every tool result is the text a live cell would see. After
the last call, the share's files must equal the subject's start tree: fully
renamed, or with the remnant line still old for a share that holds it.

Run ``uv run python -m verification_pilot.self_trust.record --image <digest>
--work ~/.assay-vp/self-trust-record`` from ``experiments/``. The result is
written to ``raw/self_trust/logs.json``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from verification_pilot.fixtures import GROUPS, read_raw_repository
from verification_pilot.self_trust.concepts import CONCEPTS, subject_repository
from verification_pilot.self_trust.ladder import REFACTOR, RUNGS, Rung
from verification_pilot.self_trust.logs import (
    RECORDED,
    log_key,
    plan_log,
    share_files,
    start_repository,
)

_BRIDGE_SRC = Path(__file__).resolve().parents[3] / "integrations" / "pier" / "src"
if str(_BRIDGE_SRC) not in sys.path:
    sys.path.insert(0, str(_BRIDGE_SRC))

from assay_pier_bridge.agent_loop import (  # noqa: E402
    MODEL_REQUEST_SECONDS,
    DockerToolSandbox,
    LoopBounds,
    _bounded_text,
    _execute_tool,
)


def _write(root: Path, tree: dict[str, str]) -> None:
    for path, source in tree.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")


def record_all(image: str, work: Path) -> dict[str, Any]:
    repository = read_raw_repository()
    cap = LoopBounds().max_tool_output_bytes
    logs: dict[str, Any] = {}
    for concept in CONCEPTS:
        start = start_repository(repository, concept)
        for group in GROUPS:
            files = share_files(repository, concept, group)
            for holds in (False, True):
                key = log_key(concept.name, group, holds)
                root = work / key
                if root.exists():
                    shutil.rmtree(root)
                _write(root / "workspace", start)
                (root / "cache").mkdir()
                calls = plan_log(repository, concept, group, holds_remnant=holds)
                sandbox = DockerToolSandbox(root / "workspace", root / "cache", image, key)
                try:
                    outputs = []
                    for call in calls:
                        output = _execute_tool(sandbox, call.name, call.arguments, cap,
                                               MODEL_REQUEST_SECONDS)
                        if output.truncated:
                            raise RuntimeError(f"{key}: {call.name} output was truncated")
                        outputs.append(_bounded_text(output.text, cap)[0])
                finally:
                    sandbox.close()
                expected = subject_repository(repository, concept, group if holds else None)
                mismatched = [path for path in files
                              if (root / "workspace" / path).read_text(encoding="utf-8")
                              != expected[path]]
                if mismatched:
                    raise RuntimeError(f"{key}: final share files differ: {mismatched}")
                logs[key] = {"calls": [asdict(call) for call in calls], "outputs": outputs}
    return {"image": image, "logs": logs}


def record_refactor(image: str, work: Path, rung: Rung = REFACTOR) -> dict[str, Any]:
    """Every share's log, recorded once per variant, on one workspace in share order.

    A share's log may depend only on whether that share holds the omission, so
    the four variants must agree on every share they share a flag for.
    """
    cap = LoopBounds().max_tool_output_bytes
    logs: dict[str, Any] = {}
    for remnant in (None, *rung.order):
        key = f"{rung.name}-{remnant or 'none'}"
        root = work / key
        if root.exists():
            shutil.rmtree(root)
        start = rung.start_tree()
        _write(root / "workspace", start)
        (root / "cache").mkdir()
        sandbox = DockerToolSandbox(root / "workspace", root / "cache", image, key)
        tree = dict(start)
        try:
            for group in rung.order:
                omit = group == remnant
                calls = rung.plan_share(tree, group, omit=omit)
                outputs = []
                for call in calls:
                    output = _execute_tool(sandbox, call.name, call.arguments, cap,
                                           MODEL_REQUEST_SECONDS)
                    if output.truncated:
                        raise RuntimeError(f"{key}: {call.name} output was truncated")
                    outputs.append(_bounded_text(output.text, cap)[0])
                if not outputs[-1].startswith("exit=0\n"):
                    raise RuntimeError(f"{key}/{group}: checks failed: {outputs[-1][:400]}")
                entry = {"calls": [asdict(call) for call in calls], "outputs": outputs}
                share_key = log_key(rung.name, group, omit)
                if share_key in logs and logs[share_key] != entry:
                    raise RuntimeError(f"{share_key}: the log depends on another share's omission")
                logs[share_key] = entry
                tree = {path.relative_to(root / "workspace").as_posix():
                        path.read_text(encoding="utf-8")
                        for path in sorted((root / "workspace").rglob("*")) if path.is_file()}
        finally:
            sandbox.close()
        expected = rung.subject_tree(remnant)
        if tree != expected:
            differing = sorted(p for p in set(tree) | set(expected)
                               if tree.get(p) != expected.get(p))
            raise RuntimeError(f"{key}: final tree differs: {differing}")
    return {"image": image, "logs": logs}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--fixture", choices=("rename", *RUNGS), default="rename")
    args = parser.parse_args()
    if args.fixture in RUNGS:
        rung = RUNGS[args.fixture]
        refactor_logs = record_refactor(args.image, args.work.expanduser().resolve(), rung)
        rung.logs.write_text(json.dumps(refactor_logs, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
        print(json.dumps({"recorded": len(refactor_logs["logs"])}))
        return
    result = record_all(args.image, args.work.expanduser().resolve())
    RECORDED.parent.mkdir(parents=True, exist_ok=True)
    RECORDED.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"recorded": len(result["logs"])}))


if __name__ == "__main__":
    main()
