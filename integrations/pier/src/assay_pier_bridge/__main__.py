"""Bridge image entrypoint — NOT the driver a real trial runs through.

``run_one_cell`` below makes exactly one guarded model call through
``GuardedOpenRouterClient`` and writes the submitted source to a file. It
needs network access to do that, but ``container.py``'s ``DockerTrialClient``
always starts this image's container with ``--network none`` (Pier's own
``NetworkPolicyFieldsMixin`` has no egress-allowlist mode either — see
README.md, "Pier revision") — so running this module as the container's
entrypoint, against a real sandboxed container, can never reach OpenRouter.
That contradiction is intentional and permanent, not a bug to fix here: the
agent's sandbox must stay network-none, so the guarded call must be made
from the host process instead. ``host_driver.GuardedCompletionTrialClient``
is that host-side driver, and is what a real trial is actually run through
today. This module stays for local/manual smoke testing of
``GuardedOpenRouterClient`` against a real API key
(``docker run --network public ...``, deliberately outside any trial), and
as the eventual home for whatever sandboxed work a real mini-swe-agent loop
adds inside the container once that lands (see ``pier_adapter.py``'s
``known_issue``).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Final

from assay_pier_bridge.provider import GuardedOpenRouterClient, GuardedRouteError, RouteResponse

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
) -> RouteResponse:
    """Make exactly one guarded model call and write the submitted source.

    Returns the validated route response. Raises ``GuardedRouteError`` on any
    protocol violation — the caller must not retry or fall back.
    """
    with GuardedOpenRouterClient(api_key=api_key) as client:
        response = client.complete(system_prompt=system_prompt, user_message=instruction)
    submission_output.parent.mkdir(parents=True, exist_ok=True)
    submission_output.write_text(response.submission.source, encoding="utf-8")
    return response


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
