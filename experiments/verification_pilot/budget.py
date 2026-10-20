"""Operator dollar cap for the pilot's paid OpenRouter route.

Each paid request reserves its worst-case price before dispatch and settles to
the provider's billed cost afterwards. The worst case counts
``PROMPT_TOKENS_PER_BYTE`` prompt tokens for every request byte, plus a fixed
slack for provider-side formatting, priced at the route's pinned
``max_price``; completion is priced at the request's ``max_tokens``.

The ratio is calibrated, not assumed. Counting a token per byte made each
reservation of a 200 KB self-trust request about three times its real
price, so caps halted runs with most of their money unspent. Across the
1,846 billed requests recorded by 2026-10-18 (2 KB to 308 KB), ``0.6 * bytes
+ 4096`` exceeds every billed prompt; above 100 KB no request passed 0.41
tokens per byte. ``tests/test_budget.py`` re-checks this against every
committed archive. A request billed above its reservation still halts the
run, so a provider that tokenizes more densely is caught, not absorbed.

A request that the remaining cap cannot cover is refused before it is sent,
and the cell stops with ``budget_exhausted``.

A dispatched request with no billed cost, or one billed above its reservation,
keeps the larger amount charged, stops its cell, and halts the run with
``billing_uncertain``, so an unknown charge never becomes a zero. Once
halted, no new cell is admitted.

The cap is an operator spending decision, not a study condition: it is kept
out of the runtime fingerprint, so a smoke and a full shard with different
caps still pool.
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

_BRIDGE_SRC = Path(__file__).resolve().parents[2] / "integrations" / "pier" / "src"
if str(_BRIDGE_SRC) not in sys.path:
    sys.path.insert(0, str(_BRIDGE_SRC))

from assay_pier_bridge.agent_loop import (  # noqa: E402
    HAIKU_TURN_ROUTE,
    BilledResponseError,
    ModelTurn,
    OpenRouterTurnRoute,
    RepositoryAgentClient,
    _json_bytes,
)

# Provider-side tokens the request bytes do not show (tool-use preamble,
# per-message framing). Generous on purpose: it only widens the reservation.
PROMPT_TOKEN_SLACK = 4_096
PROMPT_TOKENS_PER_BYTE = Decimal("0.6")
MILLION = Decimal(1_000_000)

Halt = Literal["budget_exhausted", "billing_uncertain"]


def request_cost_bound(
    route: OpenRouterTurnRoute, *, request_bytes: int, max_output_tokens: int
) -> Decimal:
    """Worst-case billed price of one request under the route's max_price."""
    prompt_tokens = Decimal(request_bytes) * PROMPT_TOKENS_PER_BYTE + PROMPT_TOKEN_SLACK
    prompt = prompt_tokens * Decimal(str(route.max_prompt_price_per_million))
    completion = Decimal(max_output_tokens) * Decimal(
        str(route.max_completion_price_per_million))
    return (prompt + completion) / MILLION


@dataclass
class SpendGate:
    """Run-wide dollar ledger shared by every paid cell of one run."""

    max_spend_usd: Decimal
    spent_usd: Decimal = Decimal(0)
    reserved_usd: Decimal = Decimal(0)
    requests: int = 0
    refused: int = 0
    halt: Halt | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.max_spend_usd.is_finite() or self.max_spend_usd <= 0:
            raise ValueError("the spend cap must be a positive dollar amount")

    def reserve(self, bound: Decimal) -> None:
        """Hold ``bound`` for one request, or refuse it with ``budget_exhausted``."""
        with self._lock:
            if self.halt is not None:
                self.refused += 1
                raise ValueError(self.halt)
            if self.spent_usd + self.reserved_usd + bound > self.max_spend_usd:
                self.halt = "budget_exhausted"
                self.refused += 1
                raise ValueError("budget_exhausted")
            self.reserved_usd += bound
            self.requests += 1

    def settle(self, bound: Decimal, cost_usd: float | None) -> None:
        """Replace one reservation with its billed cost."""
        with self._lock:
            self.reserved_usd -= bound
            if cost_usd is None:
                self.spent_usd += bound
                self.halt = "billing_uncertain"
                return
            cost = Decimal(str(cost_usd))
            self.spent_usd += max(cost, Decimal(0))
            if cost > bound:
                self.halt = "billing_uncertain"

    def release(self, bound: Decimal) -> None:
        """Return a reservation whose request was never sent."""
        with self._lock:
            self.reserved_usd -= bound
            self.requests -= 1

    def record(self) -> dict[str, Any]:
        with self._lock:
            return {"max_spend_usd": str(self.max_spend_usd), "spent_usd": str(self.spent_usd),
                    "requests": self.requests, "refused_requests": self.refused,
                    "halt": self.halt, "prompt_token_slack": PROMPT_TOKEN_SLACK,
                    "prompt_tokens_per_byte": str(PROMPT_TOKENS_PER_BYTE)}


@dataclass
class BudgetedAgentClient(RepositoryAgentClient):
    """The pinned repository agent with every paid request reserved first."""

    spend_gate: SpendGate | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.spend_gate is None or not self.model_route.paid_route_reachable:
            raise ValueError("a budgeted agent requires the paid route and a spend gate")

    def _openrouter_turn(
        self, messages: list[dict[str, Any]], route: OpenRouterTurnRoute = HAIKU_TURN_ROUTE,
        tools: list[dict[str, Any]] | None = None,
        *, deadline: float | None = None,
        on_dispatch: Any = None,
    ) -> ModelTurn:
        gate = self.spend_gate
        assert gate is not None
        request_bytes = len(_json_bytes({
            "messages": messages, "tools": self.tools if tools is None else tools}))
        max_output_tokens = (self.bounds.max_output_tokens if route.max_output_tokens is None
                             else min(self.bounds.max_output_tokens, route.max_output_tokens))
        bound = request_cost_bound(route, request_bytes=request_bytes,
                                   max_output_tokens=max_output_tokens)
        gate.reserve(bound)
        dispatched = False

        def dispatch() -> None:
            nonlocal dispatched
            dispatched = True
            if on_dispatch is not None:
                on_dispatch()

        try:
            turn = super()._openrouter_turn(messages, route, tools, deadline=deadline,
                                            on_dispatch=dispatch)
        except BilledResponseError as error:
            cost = error.usage.get("cost_usd")
            gate.settle(bound, float(cost) if cost is not None else None)
            raise
        except BaseException:
            if dispatched:
                gate.settle(bound, None)
            else:
                gate.release(bound)
            raise
        gate.settle(bound, turn.cost_usd)
        if gate.halt == "billing_uncertain":
            # A billed cost the reservation did not cover breaks the cap's
            # guarantee; the charge is kept and the cell stops here.
            raise ValueError("billing_uncertain")
        return turn
