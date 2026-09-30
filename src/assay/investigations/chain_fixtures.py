# ruff: noqa: E501
"""Chained DRY scenarios: does one slip compound as the model's own code piles up?

Each dose subject gets five successive additions in one cell. The first is the
subject's original task; the next four ask for closely related functions that
need the same abstraction. After every addition the model's source is appended
to the target file under the step's name, so later steps see the earlier ones.
Arms are starting files from the placement layout.
"""

from __future__ import annotations

from assay.investigations.consistency import ChainStep, CodingTask
from assay.investigations.dose_fixtures import (
    DOSE_TASKS,
    PLACEMENT_LAYOUT,
    dose_repository_variants,
)

CHAIN_ARMS = ("mess-00", "tail-03", "tail-07")

_ROUTE_STEPS = {
    "ticket-close": (
        "close_ticket_route",
        "the route that closes the ticket",
        (
            (
                "close_ticket_v2_route",
                'a v2 route that closes the ticket whose id is request["query"]["ticket"].',
            ),
            (
                "bulk_close_ticket_route",
                'a bulk-action route that closes the ticket whose id is request["body"]["ticket_id"].',
            ),
            (
                "admin_close_ticket_route",
                'an admin route that closes the ticket whose id is request["path"]["ticket"].',
            ),
            (
                "webhook_close_ticket_route",
                'a webhook route that closes the ticket whose id is request["payload"]["ticket"]["id"].',
            ),
        ),
    ),
    "book-return": (
        "return_book_route",
        "the route that checks in a returned book",
        (
            (
                "return_book_v2_route",
                'a v2 route that checks in the returned book whose id is request["query"]["book"].',
            ),
            (
                "kiosk_return_route",
                'a self-service kiosk route that checks in the returned book whose id is request["body"]["book_id"].',
            ),
            (
                "admin_return_book_route",
                'an admin route that checks in the returned book whose id is request["path"]["book"].',
            ),
            (
                "scanner_return_route",
                'a barcode-scanner route that checks in the returned book whose id is request["payload"]["scan"]["book_id"].',
            ),
        ),
    ),
    "stock-reserve": (
        "reserve_stock_route",
        "the route that reserves stock",
        (
            (
                "reserve_stock_v2_route",
                'a v2 route that reserves request["body"]["quantity"] units of the product whose id is request["query"]["product"].',
            ),
            (
                "checkout_reserve_route",
                'a checkout route that reserves request["body"]["qty"] units of the product whose id is request["body"]["product_id"].',
            ),
            (
                "admin_reserve_route",
                'an admin route that reserves request["body"]["quantity"] units of the product whose id is request["path"]["product"].',
            ),
            (
                "webhook_reserve_route",
                'a webhook route that reserves request["payload"]["line"]["quantity"] units of the product whose id is request["payload"]["line"]["product_id"].',
            ),
        ),
    ),
    "event-rename": (
        "rename_event_route",
        "the route that renames an event",
        (
            (
                "rename_event_v2_route",
                'a v2 route that renames the event whose id is request["query"]["event"] to request["body"]["title"].',
            ),
            (
                "inline_edit_rename_route",
                'an inline-edit route that renames the event whose id is request["body"]["event_id"] to request["body"]["value"].',
            ),
            (
                "admin_rename_event_route",
                'an admin route that renames the event whose id is request["path"]["event"] to request["body"]["title"].',
            ),
            (
                "webhook_rename_event_route",
                'a webhook route that renames the event whose id is request["payload"]["event"]["id"] to request["payload"]["event"]["title"].',
            ),
        ),
    ),
}

_OTHER_STEPS = {
    "free-shipping": (
        "qualifies_for_free_shipping",
        (
            (
                "formatted_order_total",
                "implement(order) returning the order total formatted with format_cents.",
            ),
            (
                "free_shipping_gap",
                "implement(order) returning how many cents the order total is short of FREE_SHIPPING_THRESHOLD_CENTS, or 0 if it already qualifies.",
            ),
            (
                "order_total_record",
                'implement(order) returning {"id": order["id"], "total_cents": <the order total>}.',
            ),
            (
                "over_budget",
                'implement(order) returning whether the order total exceeds order["budget_cents"].',
            ),
        ),
    ),
    "net-pay-dollars": (
        "net_pay_in_dollars",
        (
            (
                "net_pay_label",
                "implement(timesheet) returning the employee's net pay formatted with format_cents.",
            ),
            (
                "high_earner",
                "implement(timesheet) returning whether the employee's net pay is at least 100000 cents.",
            ),
            (
                "net_pay_record",
                'implement(timesheet) returning {"employee": timesheet["employee"], "net_cents": <the net pay>}.',
            ),
            (
                "net_after_advance",
                'implement(timesheet) returning the employee\'s net pay minus timesheet["advance_cents"].',
            ),
        ),
    ),
    "parcel-quote-rounded": (
        "rounded_quote",
        (
            (
                "quote_label",
                "implement(parcel) returning the parcel's shipping quote formatted with format_cents.",
            ),
            (
                "is_expensive",
                "implement(parcel) returning whether the parcel's shipping quote exceeds 1500 cents.",
            ),
            (
                "quote_dollars",
                "implement(parcel) returning the parcel's shipping quote in whole dollars, rounded down.",
            ),
            (
                "quote_with_tip",
                'implement(parcel) returning the parcel\'s shipping quote plus parcel["tip_cents"].',
            ),
        ),
    ),
    "renewal-budget": (
        "renewal_within_budget",
        (
            (
                "renewal_label",
                "implement(subscription) returning the renewal amount formatted with format_cents.",
            ),
            (
                "renewal_dollars",
                "implement(subscription) returning the renewal amount in whole dollars, rounded down.",
            ),
            (
                "renewal_record",
                'implement(subscription) returning {"account": subscription["account"], "renewal_cents": <the renewal amount>}.',
            ),
            (
                "renewal_after_credit",
                'implement(subscription) returning the renewal amount minus subscription["credit_cents"].',
            ),
        ),
    ),
    "email-key": (
        "email_key",
        (
            (
                "backup_email_key",
                'implement(payload) returning payload["backup_email"] with surrounding whitespace removed and lowercased.',
            ),
            (
                "emails_match",
                'implement(pair) returning whether pair["a"] and pair["b"] are equal once each is trimmed and lowercased.',
            ),
            (
                "contact_lookup",
                'implement(payload) returning {"email": <payload["contact"] trimmed and lowercased>}.',
            ),
            (
                "referrer_key",
                'implement(payload) returning payload["referrer"] with surrounding whitespace removed and lowercased.',
            ),
        ),
    ),
    "sku-key": (
        "sku_key",
        (
            (
                "replacement_sku_key",
                'implement(line) returning line["replacement_sku"] trimmed, uppercased, and with spaces replaced by hyphens.',
            ),
            (
                "skus_match",
                'implement(pair) returning whether pair["a"] and pair["b"] are equal once each is trimmed, uppercased, and has spaces replaced by hyphens.',
            ),
            (
                "vendor_sku_record",
                'implement(line) returning {"sku": <line["vendor_sku"] trimmed, uppercased, spaces replaced by hyphens>}.',
            ),
            (
                "parent_sku_key",
                'implement(line) returning line["parent_sku"] trimmed, uppercased, and with spaces replaced by hyphens.',
            ),
        ),
    ),
    "sample-count": (
        "sample_count",
        (
            (
                "dropped_count",
                'implement(sample) returning sample["dropped"] parsed as a trimmed base-10 integer, with negative counts floored at zero.',
            ),
            (
                "attempts_total",
                'implement(sample) returning the sum of sample["count"] and sample["retries"], each parsed as a trimmed base-10 integer floored at zero.',
            ),
            (
                "too_many_errors",
                'implement(sample) returning whether sample["errors"], parsed as a trimmed base-10 integer floored at zero, exceeds 10.',
            ),
            (
                "count_record",
                'implement(sample) returning {"count": <sample["count"] parsed as a trimmed base-10 integer floored at zero>}.',
            ),
        ),
    ),
    "postal-prefix": (
        "postcode_prefix",
        (
            (
                "billing_prefix",
                'implement(address) returning the first three characters of address["billing_postcode"] after removing spaces and uppercasing.',
            ),
            (
                "prefixes_match",
                'implement(pair) returning whether the first three characters of pair["a"] and pair["b"] match after removing spaces and uppercasing each.',
            ),
            (
                "prefix_record",
                'implement(address) returning {"prefix": <the first three characters of address["postcode"] after removing spaces and uppercasing>}.',
            ),
            (
                "delivery_prefix",
                'implement(address) returning the first three characters of address["delivery_postcode"] after removing spaces and uppercasing.',
            ),
        ),
    ),
}


def _chain(task: CodingTask) -> tuple[ChainStep, ...]:
    prefix = f"In {task.target_path}, add "
    rest: tuple[tuple[str, str], ...]
    if task.id in _ROUTE_STEPS:
        first_name, _, routes = _ROUTE_STEPS[task.id]
        rest = tuple((name, f"implement(request), {text}") for name, text in routes)
    else:
        first_name, rest = _OTHER_STEPS[task.id]
    return (
        ChainStep(instruction=task.instruction, name=first_name),
        *(ChainStep(instruction=prefix + text, name=name) for name, text in rest),
    )


CHAIN_TASKS: tuple[CodingTask, ...] = tuple(
    task.model_copy(update={"chain": _chain(task)}) for task in DOSE_TASKS
)
CHAIN_STEPS = 5


def chain_repository_variants() -> dict[str, dict[str, dict[str, str]]]:
    """The placement starting files for each chain arm."""
    layout = {arm: PLACEMENT_LAYOUT[arm] for arm in CHAIN_ARMS}
    return dose_repository_variants(layout)
