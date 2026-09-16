"""Bridge image entrypoint: the end-to-end one-cell driver.

Runs entirely against the environment frozen into the image at build time —
it never installs, resolves, or touches a pricing map. This is the in-
container half of a trial: it reads the sealed package mounted read-only at
``/workspace`` (see ``assay.pier_packaging``), makes exactly one guarded
model call through ``GuardedOpenRouterClient`` (mirroring the ``step_limit: 1``
in ``config/mini.yaml``), and writes the submitted source to
``/submission/output``. The container's lifecycle (start, resource limits,
teardown) is driven from outside by a ``PierTrialClient`` — see
``container.py`` for the concrete stand-in this project ships in place of
a real Pier client (README.md, "Known gap").
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Final

from assay_pier_bridge.provider import GuardedOpenRouterClient, GuardedRouteError

WORKSPACE_INSTRUCTION: Final = Path("/workspace/instruction.md")
SUBMISSION_OUTPUT: Final = Path("/submission/output")
DEFAULT_SYSTEM_PROMPT_PATH: Final = Path("/bridge/config/system_prompt.md")
FALLBACK_SYSTEM_PROMPT: Final = (
    "You are working inside a single trial. Read instruction.md in your "
    "workspace root for the task, and call submit_output exactly once with "
    "your final answer."
)


def run_one_cell(
    *,
    instruction: str,
    system_prompt: str,
    api_key: str,
    submission_output: Path,
) -> str:
    """Make exactly one guarded model call and write the submitted source.

    Returns the submitted source. Raises ``GuardedRouteError`` on any
    protocol violation — the caller must not retry or fall back.
    """
    with GuardedOpenRouterClient(api_key=api_key) as client:
        response = client.complete(system_prompt=system_prompt, user_message=instruction)
    submission_output.parent.mkdir(parents=True, exist_ok=True)
    submission_output.write_text(response.submission.source, encoding="utf-8")
    return response.submission.source


def main() -> int:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        sys.stderr.write("OPENROUTER_API_KEY is required\n")
        return 1
    if not WORKSPACE_INSTRUCTION.is_file():
        sys.stderr.write(f"no instruction found at {WORKSPACE_INSTRUCTION}\n")
        return 1
    instruction = WORKSPACE_INSTRUCTION.read_text(encoding="utf-8")
    system_prompt = (
        DEFAULT_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        if DEFAULT_SYSTEM_PROMPT_PATH.is_file()
        else FALLBACK_SYSTEM_PROMPT
    )
    try:
        run_one_cell(
            instruction=instruction,
            system_prompt=system_prompt,
            api_key=api_key,
            submission_output=SUBMISSION_OUTPUT,
        )
    except GuardedRouteError as error:
        sys.stderr.write(json.dumps({"error": error.reason}) + "\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
