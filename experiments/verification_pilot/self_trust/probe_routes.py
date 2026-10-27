"""One-request identity probe for named paid routes.

Each request goes through the bridge's own budgeted request path, which pins
the endpoint (ZDR, no data collection, one provider, no fallbacks, required
parameters, ``max_price``) and refuses a reply whose ``model`` or ``provider``
differs from the pin (``provider_identity``). The tool schema is the pilot's
T1 surface, so an endpoint that drops tool calling fails here rather than in a
cell. Every request is reserved against one run-wide spend gate.

Run ``uv run python -m verification_pilot.self_trust.probe_routes --route NAME
... --max-spend-usd 0.10`` from ``experiments/`` with ``OPENROUTER_API_KEY``
set. Each invocation writes a new dated file under ``raw/self_trust``.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from verification_pilot.bridge import create_pilot_agent
from verification_pilot.budget import SpendGate
from verification_pilot.run import PAID_ROUTES, _spend_cap, paid_model_route
from verification_pilot.settings import VerificationPilotSettings

RESULT_ROOT = Path(__file__).resolve().parents[1] / "raw" / "self_trust"


def write_result(result: dict[str, Any], root: Path | None = None) -> Path:
    """Keep every route probe, including probes started in the same second."""
    root = RESULT_ROOT if root is None else root
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    path = root / f"route-probes-{stamp}-{uuid4().hex}.json"
    with path.open("x", encoding="utf-8") as output:
        output.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return path


def probe(name: str, gate: SpendGate, api_key: str, runs_root: Path) -> dict[str, Any]:
    agent = create_pilot_agent(
        settings=VerificationPilotSettings(), image="sha256:" + "0" * 64, runs_root=runs_root,
        model_route=paid_model_route(name), completion=None, next_user_turns=("T2", "T3"),
        api_key=api_key, spend_gate=gate,
    )
    route = agent.paid_turn_route
    entry: dict[str, Any] = {"route": name, "model": route.model, "provider": route.provider,
                             "provider_name": route.provider_name}
    try:
        turn = agent._openrouter_turn(
            [{"role": "user", "content": "Reply with the single word: ok"}], route, agent.tools)
    except (ValueError, RuntimeError) as error:
        return {**entry, "ok": False, "error": f"{type(error).__name__}: {error}"}
    return {**entry, "ok": True, "finish_reason": turn.finish_reason,
            "prompt_tokens": turn.prompt_tokens, "completion_tokens": turn.completion_tokens,
            "cost_usd": turn.cost_usd}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route", action="append", choices=sorted(PAID_ROUTES), required=True)
    parser.add_argument("--max-spend-usd", type=_spend_cap, required=True)
    parser.add_argument("--runs-root", type=Path, default=Path("~/.assay-vp/probe-runs"))
    args = parser.parse_args()
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        parser.error("OPENROUTER_API_KEY is required")
    gate = SpendGate(Decimal(args.max_spend_usd))
    runs_root = args.runs_root.expanduser()
    runs_root.mkdir(parents=True, exist_ok=True)
    probes = [probe(name, gate, api_key, runs_root) for name in args.route]
    spend = gate.record()
    result = {"probed_at": datetime.now(UTC).isoformat(timespec="seconds"), "probes": probes,
              "spend": spend}
    path = write_result(result)
    print(json.dumps({"ok": [p["route"] for p in probes if p["ok"]],
                      "failed": {p["route"]: p.get("error") for p in probes if not p["ok"]},
                      "spent_usd": spend["spent_usd"], "result": str(path)}))


if __name__ == "__main__":
    main()
