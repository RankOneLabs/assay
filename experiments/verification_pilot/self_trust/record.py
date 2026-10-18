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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    result = record_all(args.image, args.work.expanduser().resolve())
    RECORDED.parent.mkdir(parents=True, exist_ok=True)
    RECORDED.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"recorded": len(result["logs"])}))


if __name__ == "__main__":
    main()
