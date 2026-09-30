# ruff: noqa: E501
"""Dose-response DRY scenarios: how much bypassing code before a model follows it?

The twelve layered subjects are rebuilt with ten existing callers of the
reusable unit in each target file. Arm ``mess-NN`` writes NN of those callers
inline and the rest through the abstraction; everything else in the repository
is identical across arms. Messy callers are spread through the file, each
level's set contains the previous level's, and the caller nearest the end of
the file, where the model's code is appended, stays clean until ``mess-10``.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from textwrap import dedent, indent

from assay.investigations.consistency import CodingTask
from assay.investigations.layered_fixtures import (
    _ACCOUNTS,
    _ADDRESSES,
    _BILLING,
    _CALENDAR,
    _CATALOG,
    _HELPDESK,
    _INVENTORY,
    _LIBRARY,
    _PARCELS,
    _PAYROLL,
    _STOREFRONT,
    _TELEMETRY,
    LAYERED_TASKS,
)

MESS_POSITIONS: dict[int, tuple[int, ...]] = {
    0: (),
    1: (4,),
    3: (0, 4, 8),
    5: (0, 2, 4, 6, 8),
    7: (0, 1, 2, 4, 6, 7, 8),
    10: tuple(range(10)),
}
DOSE_ARMS = tuple(f"mess-{level:02d}" for level in MESS_POSITIONS)


def _source(text: str) -> str:
    return dedent(text).strip("\n") + "\n"


def _imports(names: Mapping[str, set[str]]) -> str:
    lines = []
    for module in sorted(names):
        members = sorted(names[module])
        line = f"from {module} import {', '.join(members)}"
        if len(line) > 88:
            line = f"from {module} import (\n" + "".join(f"    {m},\n" for m in members) + ")"
        lines.append(line)
    return "\n".join(lines)


def _merge(*groups: Mapping[str, set[str]]) -> dict[str, set[str]]:
    merged: dict[str, set[str]] = {}
    for group in groups:
        for module, members in group.items():
            merged.setdefault(module, set()).update(members)
    return merged


@dataclass(frozen=True)
class _Target:
    """A target file whose ten callers render clean or inline."""

    docstring: str
    constants: str
    distractors: str
    always: Mapping[str, set[str]]
    clean_imports: Mapping[str, set[str]]
    inline_imports: Mapping[str, set[str]]
    callers: tuple[tuple[str, str], ...]  # (clean, inline) function sources
    # Optional (clean, inline) imports per caller, replacing the shared sets above,
    # so a file never imports a name only its other rendering would use.
    caller_imports: tuple[tuple[Mapping[str, set[str]], Mapping[str, set[str]]], ...] = ()

    def render(self, level: int) -> str:
        messy = set(MESS_POSITIONS[level])
        if self.caller_imports:
            imports = _merge(
                self.always,
                *(
                    inline if index in messy else clean
                    for index, (clean, inline) in enumerate(self.caller_imports)
                ),
            )
        else:
            imports = _merge(
                self.always,
                self.clean_imports if len(messy) < 10 else {},
                self.inline_imports if messy else {},
            )
        functions = [
            inline if index in messy else clean
            for index, (clean, inline) in enumerate(self.callers)
        ]
        parts = [f'"""{self.docstring}"""', _imports(imports)]
        if self.constants:
            parts.append(self.constants.strip("\n"))
        body = "\n\n\n".join(
            fn.strip("\n") for fn in (*_source(self.distractors).split("\n\n\n"), *functions)
        )
        return "\n\n".join(parts) + "\n\n\n" + body + "\n"


# --- cross-module: one-line helpers --------------------------------------------


def _expand_marker(template: str, render: Callable[[str], str]) -> str:
    """Replace every ``H(<arg>)`` with ``render(<arg>)``, respecting nested brackets."""
    out, index = [], 0
    while (start := template.find("H(", index)) != -1:
        out.append(template[index:start])
        depth, cursor = 1, start + 2
        while depth:
            depth += {"(": 1, ")": -1}.get(template[cursor], 0)
            cursor += 1
        out.append(render(template[start + 2 : cursor - 1]))
        index = cursor
    out.append(template[index:])
    return "".join(out)


def _helper_callers(
    helper: str, inline: Callable[[str], str], templates: Sequence[str]
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (
            _expand_marker(_source(template), lambda arg: f"{helper}({arg})"),
            _expand_marker(_source(template), inline),
        )
        for template in templates
    )


_EMAIL = _Target(
    docstring="Request handlers for signup, invitations and account merging.",
    constants='BLOCKED_EMAILS = frozenset({"noreply@example.com"})\nMAX_DISPLAY_NAME = 40\n',
    distractors="""
        def confirmation_notice(payload):
            return f"We sent a link to {mask_email(payload['email'])}"


        def display_name(payload):
            return payload.get("name", "")[:MAX_DISPLAY_NAME]
    """,
    always={"accounts.utils": {"mask_email"}},
    clean_imports={"accounts.utils": {"normalize_email"}},
    inline_imports={},
    callers=_helper_callers(
        "normalize_email",
        lambda arg: f"{arg}.strip().lower()",
        (
            'def signup_key(payload):\n    return H(payload["email"])',
            'def invite_key(invite):\n    return H(invite["address"])',
            'def same_account(pair):\n    return H(pair["first"]) == H(pair["second"])',
            'def login_lookup(request):\n    return {"email": H(request["username"])}',
            'def is_blocked(payload):\n    return H(payload["email"]) in BLOCKED_EMAILS',
            'def recovery_target(account):\n    return H(account["recovery_email"])',
            'def billing_contact(org):\n    return {"org": org["id"], "email": H(org["billing_email"])}',
            'def newsletter_row(subscriber):\n    return [H(subscriber["email"]), subscriber.get("name", "")]',
            'def owner_matches(pair):\n    return H(pair["owner"]) == H(pair["actor"])',
            'def audit_actor(event):\n    return event["kind"] + ":" + H(event["actor"])',
        ),
    ),
)

_SKU = _Target(
    docstring="Handlers for imports, API lookups and listing pages.",
    constants='DISCONTINUED_SKUS = frozenset({"OLD-1"})\nLISTING_TITLE_WIDTH = 32\n',
    distractors="""
        def listing_title(product):
            return truncate(product["name"], LISTING_TITLE_WIDTH)
    """,
    always={"catalog.utils": {"price_label", "truncate"}},
    clean_imports={"catalog.utils": {"canonical_sku"}},
    inline_imports={},
    callers=_helper_callers(
        "canonical_sku",
        lambda arg: f'{arg}.strip().upper().replace(" ", "-")',
        (
            'def import_row_sku(row):\n    return H(row["sku"])',
            'def api_lookup_key(request):\n    return H(request["query"]["sku"])',
            'def same_sku(pair):\n    return H(pair["first"]) == H(pair["second"])',
            'def barcode_label(product):\n    return {"sku": H(product["sku"]), "name": product["name"]}',
            'def is_discontinued(product):\n    return H(product["sku"]) in DISCONTINUED_SKUS',
            'def supplier_key(offer):\n    return offer["supplier"] + "/" + H(offer["sku"])',
            'def bundle_skus(bundle):\n    return [H(bundle["primary"]), H(bundle["secondary"])]',
            'def search_token(query):\n    return H(query["text"])',
            'def warehouse_slot(item):\n    return {"slot": item["bin"], "sku": H(item["sku"])}',
            'def price_row(product):\n    return [H(product["sku"]), price_label(product["price_cents"])]',
        ),
    ),
)

_COUNT = _Target(
    docstring="Handlers for incoming metric samples.",
    constants="ERROR_BUDGET = 50\nIDLE_RATIO = 0.05\nQUOTA = 10_000\n",
    distractors="""
        def is_saturated(sample):
            return parse_ratio(sample["utilisation"]) > 1 - IDLE_RATIO
    """,
    always={"telemetry.utils": {"parse_ratio"}},
    clean_imports={"telemetry.utils": {"parse_count"}},
    inline_imports={},
    callers=_helper_callers(
        "parse_count",
        lambda arg: f"max(0, int({arg}.strip()))",
        (
            'def ingest_sample(sample):\n    return {"metric": sample["metric"], "count": H(sample["count"])}',
            'def merge_counts(pair):\n    return H(pair["first"]) + H(pair["second"])',
            'def is_idle(sample):\n    return H(sample["count"]) == 0',
            'def counter_delta(pair):\n    return H(pair["after"]) - H(pair["before"])',
            'def exceeds_quota(sample):\n    return H(sample["count"]) > QUOTA',
            'def batch_size(header):\n    return H(header["x-batch-size"])',
            'def error_budget_left(sample):\n    return max(0, ERROR_BUDGET - H(sample["errors"]))',
            'def histogram_bucket(sample):\n    return min(H(sample["count"]) // 10, 9)',
            'def retry_count(job):\n    return H(job["retries"])',
            'def series_point(sample):\n    return [sample["ts"], H(sample["count"])]',
        ),
    ),
)

_POSTAL = _Target(
    docstring="Handlers for sorting and routing addresses.",
    constants='DEPOTS = {"SW1": "west", "E16": "east"}\nREMOTE_PREFIXES = frozenset({"ZE1", "HS1"})\n',
    distractors="""
        def destination(address):
            return country_name(address["country"])
    """,
    always={"addresses.utils": {"country_name"}},
    clean_imports={"addresses.utils": {"postal_prefix"}},
    inline_imports={},
    callers=_helper_callers(
        "postal_prefix",
        lambda arg: f'{arg}.replace(" ", "").upper()[:3]',
        (
            'def sorting_bin(address):\n    return H(address["postcode"])',
            'def same_district(pair):\n    return H(pair["first"]) == H(pair["second"])',
            'def route_key(address):\n    return address["country"] + "-" + H(address["postcode"])',
            'def depot_for(address):\n    return DEPOTS.get(H(address["postcode"]), "central")',
            'def is_remote(address):\n    return H(address["postcode"]) in REMOTE_PREFIXES',
            'def manifest_row(parcel):\n    return [parcel["id"], H(parcel["postcode"])]',
            'def courier_zone(address):\n    return {"zone": H(address["postcode"]), "country": address["country"]}',
            'def billing_region(account):\n    return H(account["billing_postcode"])',
            'def return_origin(shipment):\n    return H(shipment["from_postcode"])',
            'def van_route(stop):\n    return stop["van"] + ":" + H(stop["postcode"])',
        ),
    ),
)


# --- domain-rule: composite rules ----------------------------------------------


def _rule_callers(
    call: str, prelude: str, result: str, templates: Sequence[tuple[str, str]]
) -> tuple[tuple[str, str], ...]:
    """Each template is (signature, return expression with ``@V@`` for the rule's value)."""
    prelude_lines = indent(_source(prelude), "    ")
    return tuple(
        (
            f"def {signature}:\n    return {expression.replace('@V@', call)}\n",
            f"def {signature}:\n{prelude_lines}    return {expression.replace('@V@', result)}\n",
        )
        for signature, expression in templates
    )


_SHIPPING = _Target(
    docstring="Order reporting for finance and customer-service tooling.",
    constants=(
        "FREE_SHIPPING_THRESHOLD_CENTS = 5000\nINSTALLMENTS = 3\n"
        "LARGE_ORDER_CENTS = 100_000\nREVIEW_THRESHOLD_CENTS = 250_000\n"
    ),
    distractors="""
        def item_count(order):
            return sum(line["quantity"] for line in order["lines"])
    """,
    always={"storefront.formatting": {"format_cents"}},
    clean_imports={"storefront.pricing": {"order_total"}},
    inline_imports={"storefront.pricing": {"discount_for", "line_amount", "tax_on"}},
    callers=_rule_callers(
        "order_total(order)",
        """
        subtotal = sum(line_amount(line) for line in order["lines"])
        discounted = subtotal - discount_for(order.get("coupon"), subtotal)
        total = discounted + tax_on(discounted)
        """,
        "total",
        (
            ("invoice_line(order)", '"Order " + order["id"] + ": " + format_cents(@V@)'),
            ("loyalty_points(order)", "@V@ // 100"),
            ("needs_manual_review(order)", "@V@ > REVIEW_THRESHOLD_CENTS"),
            ("payment_intent(order)", '{"order": order["id"], "amount_cents": @V@}'),
            ("installment_amount(order)", "-(-@V@ // INSTALLMENTS)"),
            ("gift_card_covers(order)", 'order.get("gift_card_cents", 0) >= @V@'),
            ("fraud_features(order)", '[order["id"], len(order["lines"]), @V@]'),
            ("receipt_total(order)", "format_cents(@V@)"),
            ("is_large_order(order)", "@V@ >= LARGE_ORDER_CENTS"),
            ("refundable_cents(order)", '@V@ - order.get("refunded_cents", 0)'),
        ),
    ),
)

_NET_PAY = _Target(
    docstring="Payslips and bank instructions for a pay period.",
    constants=(
        "BONUS_THRESHOLD_CENTS = 150_000\nGARNISH_PERCENT = 10\n"
        "MINIMUM_NET_CENTS = 40_000\nPENSION_PERCENT = 5\n"
    ),
    distractors="""
        def overtime_hours(timesheet):
            return max(timesheet["hours"] - OVERTIME_THRESHOLD_HOURS, 0)
    """,
    always={"payroll.formatting": {"format_cents"}, "payroll.rules": {"OVERTIME_THRESHOLD_HOURS"}},
    clean_imports={"payroll.rules": {"net_pay"}},
    inline_imports={"payroll.rules": {"benefit_deduction", "gross_pay", "withholding"}},
    callers=_rule_callers(
        "net_pay(timesheet)",
        """
        gross = gross_pay(timesheet["hours"], timesheet["rate_cents"])
        net = gross - withholding(gross) - benefit_deduction(timesheet.get("plan"))
        """,
        "net",
        (
            ("payslip_line(timesheet)", 'timesheet["employee"] + ": " + format_cents(@V@)'),
            (
                "deposit_instruction(timesheet)",
                '{"employee": timesheet["employee"], "amount_cents": @V@}',
            ),
            ("below_minimum(timesheet)", "@V@ < MINIMUM_NET_CENTS"),
            ("garnishment_cents(timesheet)", "@V@ * GARNISH_PERCENT // 100"),
            ("hourly_net(timesheet)", '@V@ // max(timesheet["hours"], 1)'),
            ("bonus_eligible(timesheet)", "@V@ >= BONUS_THRESHOLD_CENTS"),
            ("ledger_row(timesheet)", '[timesheet["employee"], timesheet["hours"], @V@]'),
            ("advance_limit(timesheet)", "@V@ // 2"),
            ("pension_contribution(timesheet)", "@V@ * PENSION_PERCENT // 100"),
            (
                "net_summary(timesheet)",
                '{"employee": timesheet["employee"], "net": format_cents(@V@)}',
            ),
        ),
    ),
)

_PARCEL = _Target(
    docstring="Dispatch manifests, labels and customs paperwork.",
    constants=(
        "HEAVY_GRAMS = 20_000\nMAX_QUOTE_CENTS = 10_000\n"
        "PREMIUM_CENTS = 2000\nRESELLER_SHARE_PERCENT = 15\n"
    ),
    distractors="""
        def is_heavy(parcel):
            return parcel["grams"] > HEAVY_GRAMS
    """,
    always={"parcels.formatting": {"format_cents"}},
    clean_imports={"parcels.rates": {"parcel_quote"}},
    inline_imports={"parcels.rates": {"fuel_surcharge", "weight_surcharge", "zone_rate"}},
    callers=_rule_callers(
        "parcel_quote(parcel)",
        """
        base = zone_rate(parcel["zone"]) + weight_surcharge(parcel["grams"])
        quote = base + fuel_surcharge(base)
        """,
        "quote",
        (
            (
                "label_line(parcel)",
                'parcel["tracking"] + " " + parcel["zone"] + " " + format_cents(@V@)',
            ),
            (
                "customs_declaration(parcel)",
                '{"tracking": parcel["tracking"], "shipping_cents": @V@}',
            ),
            ("cash_on_delivery(parcel)", 'parcel.get("goods_cents", 0) + @V@'),
            ("invoice_row(parcel)", '[parcel["tracking"], @V@]'),
            ("exceeds_budget(parcel)", '@V@ > parcel.get("budget_cents", MAX_QUOTE_CENTS)'),
            ("is_premium(parcel)", "@V@ >= PREMIUM_CENTS"),
            ("reseller_share(parcel)", "@V@ * RESELLER_SHARE_PERCENT // 100"),
            (
                "driver_entry(parcel)",
                '{"tracking": parcel["tracking"], "charge": format_cents(@V@)}',
            ),
            ("quote_with_insurance(parcel)", '@V@ + parcel.get("insured_cents", 0) // 100'),
            (
                "quote_message(parcel)",
                '"Shipping " + parcel["tracking"] + " costs " + format_cents(@V@)',
            ),
        ),
    ),
)

_RENEWAL = _Target(
    docstring="Renewal notices, invoice drafts and approval routing.",
    constants=(
        "APPROVAL_LIMIT_CENTS = 500_000\nENTERPRISE_DEAL_CENTS = 1_000_000\nSALES_TAX_PERCENT = 8\n"
    ),
    distractors="""
        def is_known_plan(subscription):
            return subscription["plan"] in PLAN_SEAT_CENTS
    """,
    always={"billing.formatting": {"format_cents"}, "billing.plans": {"PLAN_SEAT_CENTS"}},
    clean_imports={"billing.plans": {"renewal_amount"}},
    inline_imports={"billing.plans": {"annual_price", "seat_price", "volume_discount"}},
    callers=_rule_callers(
        "renewal_amount(subscription)",
        """
        seats = subscription["seats"]
        amount = seat_price(subscription["plan"]) * seats
        amount -= volume_discount(seats, amount)
        if subscription.get("annual"):
            amount = annual_price(amount)
        """,
        "amount",
        (
            (
                "renewal_notice(subscription)",
                'subscription["account"] + " renews at " + format_cents(@V@)',
            ),
            (
                "invoice_draft(subscription)",
                '{"account": subscription["account"], "amount_cents": @V@}',
            ),
            ("requires_approval(subscription)", "@V@ > APPROVAL_LIMIT_CENTS"),
            ("per_seat_cost(subscription)", '@V@ // subscription["seats"]'),
            ("sales_tax(subscription)", "@V@ * SALES_TAX_PERCENT // 100"),
            ("forecast_row(subscription)", '[subscription["account"], subscription["plan"], @V@]'),
            ("credit_covers(subscription)", 'subscription.get("credit_cents", 0) >= @V@'),
            (
                "churn_features(subscription)",
                '{"seats": subscription["seats"], "amount_cents": @V@}',
            ),
            ("is_enterprise_deal(subscription)", "@V@ >= ENTERPRISE_DEAL_CENTS"),
            (
                "dunning_message(subscription)",
                '"Payment of " + format_cents(@V@) + " due for " + subscription["account"]',
            ),
        ),
    ),
)


# --- route-view: routes over views ---------------------------------------------


@dataclass(frozen=True)
class _View:
    name: str
    params: tuple[str, ...]  # subset of ("<noun>_id", "payload"), in order
    body: str


def _names(source: str) -> set[str]:
    return {
        node.id
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }


def _route_target(
    package: str,
    noun: str,
    views: Sequence[_View],
    target: _View,
    constants: str,
    docstring: str,
    distractor: str,
) -> tuple[str, _Target]:
    """Return (views.py source, routes.py target) for one domain."""
    id_param = f"{noun}_id"
    homes = {
        name: f"{package}.{module}"
        for module, members in {
            "responses": ("ok", "created", "bad_request", "not_found", "conflict"),
            "serializers": (f"serialize_{noun}",),
            "store": (f"list_{noun}s", f"load_{noun}", f"save_{noun}", f"next_{noun}_id"),
            "views": tuple(re.findall(r"^([A-Z_]+) =", constants, re.MULTILINE)),
        }.items()
        for name in members
    }

    def function(view: _View, name: str, params: str, preamble: str = "") -> str:
        return f"def {name}({params}):\n{preamble}" + indent(_source(view.body), "    ")

    view_sources = [function(view, view.name, ", ".join(view.params)) for view in (*views, target)]
    view_names: set[str] = set().union(*(_names(source) for source in view_sources))
    views_imports: dict[str, set[str]] = {}
    for name in sorted(view_names):
        module = homes.get(name)
        if module and not module.endswith(".views"):
            views_imports.setdefault(module, set()).add(name)
    views_py = (
        f'"""{noun.capitalize()} views: each takes plain arguments and returns a response '
        'envelope."""\n\n'
        + _imports(views_imports)
        + "\n\n"
        + constants.strip("\n")
        + "\n\n\n"
        + "\n\n".join(view_sources)
    )

    arguments = {id_param: 'request["id"]', "payload": 'request["body"]'}
    callers = []
    caller_imports = []
    for view in views:
        route = view.name.removesuffix("_view") + "_route"
        clean = (
            f"def {route}(request):\n"
            f"    return {view.name}({', '.join(arguments[p] for p in view.params)})\n"
        )
        preamble = "".join(f"    {param} = {arguments[param]}\n" for param in view.params)
        inline = function(view, route, "request", preamble)
        callers.append((clean, inline))
        inline_imports: dict[str, set[str]] = {}
        for name in _names(inline):
            if name in homes:
                inline_imports.setdefault(homes[name], set()).add(name)
        caller_imports.append(({f"{package}.views": {view.name}}, inline_imports))
    return views_py, _Target(
        docstring=docstring,
        constants="",
        distractors=distractor,
        always={f"{package}.responses": {"ok"}},
        clean_imports={},
        inline_imports={},
        callers=tuple(callers),
        caller_imports=tuple(caller_imports),
    )


_HELPDESK_VIEWS, _TICKET_ROUTES = _route_target(
    "helpdesk",
    "ticket",
    (
        _View("list_tickets_view", (), "return ok([serialize_ticket(t) for t in list_tickets()])"),
        _View(
            "list_open_tickets_view",
            (),
            """
            tickets = [t for t in list_tickets() if t["status"] == "open"]
            return ok([serialize_ticket(t) for t in tickets])
            """,
        ),
        _View(
            "get_ticket_view",
            ("ticket_id",),
            """
            ticket = load_ticket(ticket_id)
            if ticket is None:
                return not_found("ticket", ticket_id)
            return ok(serialize_ticket(ticket))
            """,
        ),
        _View(
            "create_ticket_view",
            ("payload",),
            """
            subject = str(payload.get("subject", "")).strip()
            if not subject:
                return bad_request("subject is required")
            priority = payload.get("priority", "normal")
            if priority not in PRIORITIES:
                return bad_request("priority must be one of " + ", ".join(PRIORITIES))
            ticket = save_ticket(
                {
                    "id": next_ticket_id(),
                    "subject": subject,
                    "status": "open",
                    "assignee": None,
                    "priority": priority,
                    "internal_notes": "",
                }
            )
            return created(serialize_ticket(ticket))
            """,
        ),
        _View(
            "assign_ticket_view",
            ("ticket_id", "payload"),
            """
            ticket = load_ticket(ticket_id)
            if ticket is None:
                return not_found("ticket", ticket_id)
            if ticket["status"] == "closed":
                return conflict(f"ticket {ticket_id} is closed")
            assignee = str(payload.get("assignee", "")).strip()
            if not assignee:
                return bad_request("assignee is required")
            ticket["assignee"] = assignee
            return ok(serialize_ticket(save_ticket(ticket)))
            """,
        ),
        _View(
            "unassign_ticket_view",
            ("ticket_id",),
            """
            ticket = load_ticket(ticket_id)
            if ticket is None:
                return not_found("ticket", ticket_id)
            if ticket["assignee"] is None:
                return conflict(f"ticket {ticket_id} is not assigned")
            ticket["assignee"] = None
            return ok(serialize_ticket(save_ticket(ticket)))
            """,
        ),
        _View(
            "set_priority_view",
            ("ticket_id", "payload"),
            """
            ticket = load_ticket(ticket_id)
            if ticket is None:
                return not_found("ticket", ticket_id)
            priority = payload.get("priority")
            if priority not in PRIORITIES:
                return bad_request("priority must be one of " + ", ".join(PRIORITIES))
            ticket["priority"] = priority
            return ok(serialize_ticket(save_ticket(ticket)))
            """,
        ),
        _View(
            "rename_ticket_view",
            ("ticket_id", "payload"),
            """
            ticket = load_ticket(ticket_id)
            if ticket is None:
                return not_found("ticket", ticket_id)
            if ticket["status"] == "closed":
                return conflict(f"ticket {ticket_id} is closed")
            subject = str(payload.get("subject", "")).strip()
            if not subject:
                return bad_request("subject is required")
            ticket["subject"] = subject
            return ok(serialize_ticket(save_ticket(ticket)))
            """,
        ),
        _View(
            "add_note_view",
            ("ticket_id", "payload"),
            """
            ticket = load_ticket(ticket_id)
            if ticket is None:
                return not_found("ticket", ticket_id)
            note = str(payload.get("note", "")).strip()
            if not note:
                return bad_request("note is required")
            ticket["internal_notes"] = (ticket["internal_notes"] + "\\n" + note).strip()
            save_ticket(ticket)
            return ok({"id": ticket_id, "notes": len(ticket["internal_notes"].splitlines())})
            """,
        ),
        _View(
            "reopen_ticket_view",
            ("ticket_id",),
            """
            ticket = load_ticket(ticket_id)
            if ticket is None:
                return not_found("ticket", ticket_id)
            if ticket["status"] == "open":
                return conflict(f"ticket {ticket_id} is already open")
            ticket["status"] = "open"
            return ok(serialize_ticket(save_ticket(ticket)))
            """,
        ),
    ),
    _View(
        "close_ticket_view",
        ("ticket_id",),
        """
        ticket = load_ticket(ticket_id)
        if ticket is None:
            return not_found("ticket", ticket_id)
        if ticket["status"] == "closed":
            return conflict(f"ticket {ticket_id} is already closed")
        ticket["status"] = "closed"
        return ok(serialize_ticket(save_ticket(ticket)))
        """,
    ),
    constants='PRIORITIES = ("low", "normal", "high")\n',
    docstring="HTTP routes for the ticket API.",
    distractor="""
        def health_route(request):
            return ok({"status": "up"})
    """,
)

_LIBRARY_VIEWS, _BOOK_ROUTES = _route_target(
    "library",
    "book",
    (
        _View("list_books_view", (), "return ok([serialize_book(b) for b in list_books()])"),
        _View(
            "list_available_books_view",
            (),
            """
            books = [b for b in list_books() if b["borrower"] is None]
            return ok([serialize_book(b) for b in books])
            """,
        ),
        _View(
            "get_book_view",
            ("book_id",),
            """
            book = load_book(book_id)
            if book is None:
                return not_found("book", book_id)
            return ok(serialize_book(book))
            """,
        ),
        _View(
            "add_book_view",
            ("payload",),
            """
            title = str(payload.get("title", "")).strip()
            author = str(payload.get("author", "")).strip()
            if not title or not author:
                return bad_request("title and author are required")
            book = save_book(
                {
                    "id": next_book_id(),
                    "title": title,
                    "author": author,
                    "borrower": None,
                    "due_day": None,
                    "acquired": payload.get("acquired"),
                }
            )
            return created(serialize_book(book))
            """,
        ),
        _View(
            "checkout_book_view",
            ("book_id", "payload"),
            """
            book = load_book(book_id)
            if book is None:
                return not_found("book", book_id)
            if book["borrower"] is not None:
                return conflict(f"book {book_id} is already checked out")
            borrower = str(payload.get("borrower", "")).strip()
            if not borrower:
                return bad_request("borrower is required")
            day = payload.get("day")
            if not isinstance(day, int):
                return bad_request("day must be an integer")
            book["borrower"] = borrower
            book["due_day"] = day + LOAN_DAYS
            return ok(serialize_book(save_book(book)))
            """,
        ),
        _View(
            "renew_book_view",
            ("book_id",),
            """
            book = load_book(book_id)
            if book is None:
                return not_found("book", book_id)
            if book["borrower"] is None:
                return conflict(f"book {book_id} is not checked out")
            book["due_day"] += LOAN_DAYS
            return ok(serialize_book(save_book(book)))
            """,
        ),
        _View(
            "retitle_book_view",
            ("book_id", "payload"),
            """
            book = load_book(book_id)
            if book is None:
                return not_found("book", book_id)
            title = str(payload.get("title", "")).strip()
            if not title:
                return bad_request("title is required")
            book["title"] = title
            return ok(serialize_book(save_book(book)))
            """,
        ),
        _View(
            "update_author_view",
            ("book_id", "payload"),
            """
            book = load_book(book_id)
            if book is None:
                return not_found("book", book_id)
            author = str(payload.get("author", "")).strip()
            if not author:
                return bad_request("author is required")
            book["author"] = author
            return ok(serialize_book(save_book(book)))
            """,
        ),
        _View(
            "books_by_author_view",
            ("payload",),
            """
            author = str(payload.get("author", "")).strip().lower()
            books = [b for b in list_books() if b["author"].lower() == author]
            return ok([serialize_book(b) for b in books])
            """,
        ),
        _View(
            "due_date_view",
            ("book_id",),
            """
            book = load_book(book_id)
            if book is None:
                return not_found("book", book_id)
            if book["borrower"] is None:
                return conflict(f"book {book_id} is not checked out")
            return ok({"id": book_id, "due_day": book["due_day"]})
            """,
        ),
    ),
    _View(
        "return_book_view",
        ("book_id",),
        """
        book = load_book(book_id)
        if book is None:
            return not_found("book", book_id)
        if book["borrower"] is None:
            return conflict(f"book {book_id} is not checked out")
        book["borrower"] = None
        book["due_day"] = None
        return ok(serialize_book(save_book(book)))
        """,
    ),
    constants="LOAN_DAYS = 21\n",
    docstring="HTTP routes for the lending API.",
    distractor="""
        def branch_route(request):
            return ok({"branch": "riverside"})
    """,
)

_INVENTORY_VIEWS, _PRODUCT_ROUTES = _route_target(
    "inventory",
    "product",
    (
        _View(
            "list_products_view", (), "return ok([serialize_product(p) for p in list_products()])"
        ),
        _View(
            "low_stock_products_view",
            (),
            """
            products = [p for p in list_products() if p["on_hand"] - p["reserved"] < LOW_STOCK]
            return ok([serialize_product(p) for p in products])
            """,
        ),
        _View(
            "get_product_view",
            ("product_id",),
            """
            product = load_product(product_id)
            if product is None:
                return not_found("product", product_id)
            return ok(serialize_product(product))
            """,
        ),
        _View(
            "find_product_by_sku_view",
            ("payload",),
            """
            sku = str(payload.get("sku", "")).strip().upper()
            for product in list_products():
                if product["sku"] == sku:
                    return ok(serialize_product(product))
            return not_found("product", sku)
            """,
        ),
        _View(
            "create_product_view",
            ("payload",),
            """
            sku = str(payload.get("sku", "")).strip().upper()
            name = str(payload.get("name", "")).strip()
            if not sku or not name:
                return bad_request("sku and name are required")
            product = save_product(
                {
                    "id": next_product_id(),
                    "sku": sku,
                    "name": name,
                    "on_hand": 0,
                    "reserved": 0,
                    "supplier": payload.get("supplier"),
                }
            )
            return created(serialize_product(product))
            """,
        ),
        _View(
            "restock_product_view",
            ("product_id", "payload"),
            """
            product = load_product(product_id)
            if product is None:
                return not_found("product", product_id)
            quantity = payload.get("quantity")
            if not isinstance(quantity, int) or quantity < 1:
                return bad_request("quantity must be a positive integer")
            product["on_hand"] += quantity
            return ok(serialize_product(save_product(product)))
            """,
        ),
        _View(
            "release_stock_view",
            ("product_id", "payload"),
            """
            product = load_product(product_id)
            if product is None:
                return not_found("product", product_id)
            quantity = payload.get("quantity")
            if not isinstance(quantity, int) or quantity < 1:
                return bad_request("quantity must be a positive integer")
            if quantity > product["reserved"]:
                return conflict(f"only {product['reserved']} of {product['sku']} reserved")
            product["reserved"] -= quantity
            return ok(serialize_product(save_product(product)))
            """,
        ),
        _View(
            "fulfil_stock_view",
            ("product_id", "payload"),
            """
            product = load_product(product_id)
            if product is None:
                return not_found("product", product_id)
            quantity = payload.get("quantity")
            if not isinstance(quantity, int) or quantity < 1:
                return bad_request("quantity must be a positive integer")
            if quantity > product["reserved"]:
                return conflict(f"only {product['reserved']} of {product['sku']} reserved")
            product["reserved"] -= quantity
            product["on_hand"] -= quantity
            return ok(serialize_product(save_product(product)))
            """,
        ),
        _View(
            "rename_product_view",
            ("product_id", "payload"),
            """
            product = load_product(product_id)
            if product is None:
                return not_found("product", product_id)
            name = str(payload.get("name", "")).strip()
            if not name:
                return bad_request("name is required")
            product["name"] = name
            return ok(serialize_product(save_product(product)))
            """,
        ),
        _View(
            "count_stock_view",
            ("product_id", "payload"),
            """
            product = load_product(product_id)
            if product is None:
                return not_found("product", product_id)
            counted = payload.get("on_hand")
            if not isinstance(counted, int) or counted < 0:
                return bad_request("on_hand must be a non-negative integer")
            if counted < product["reserved"]:
                return conflict(f"count {counted} is below {product['reserved']} reserved")
            product["on_hand"] = counted
            return ok(serialize_product(save_product(product)))
            """,
        ),
    ),
    _View(
        "reserve_stock_view",
        ("product_id", "payload"),
        """
        product = load_product(product_id)
        if product is None:
            return not_found("product", product_id)
        quantity = payload.get("quantity")
        if not isinstance(quantity, int) or quantity < 1:
            return bad_request("quantity must be a positive integer")
        available = product["on_hand"] - product["reserved"]
        if quantity > available:
            return conflict(f"only {available} of {product['sku']} available")
        product["reserved"] += quantity
        return ok(serialize_product(save_product(product)))
        """,
    ),
    constants="LOW_STOCK = 5\n",
    docstring="HTTP routes for the stock API.",
    distractor="""
        def warehouse_route(request):
            return ok({"warehouse": "north"})
    """,
)

_CALENDAR_VIEWS, _EVENT_ROUTES = _route_target(
    "calendar_api",
    "event",
    (
        _View(
            "list_events_view",
            (),
            """
            events = [e for e in list_events() if not e["cancelled"]]
            return ok([serialize_event(e) for e in events])
            """,
        ),
        _View(
            "events_on_day_view",
            ("payload",),
            """
            day = payload.get("day")
            if not isinstance(day, int):
                return bad_request("day must be an integer")
            events = [e for e in list_events() if e["day"] == day and not e["cancelled"]]
            return ok([serialize_event(e) for e in events])
            """,
        ),
        _View(
            "get_event_view",
            ("event_id",),
            """
            event = load_event(event_id)
            if event is None:
                return not_found("event", event_id)
            return ok(serialize_event(event))
            """,
        ),
        _View(
            "create_event_view",
            ("payload",),
            """
            title = str(payload.get("title", "")).strip()
            if not title:
                return bad_request("title is required")
            if len(title) > MAX_TITLE:
                return bad_request(f"title must be at most {MAX_TITLE} characters")
            day = payload.get("day")
            if not isinstance(day, int) or day < 1:
                return bad_request("day must be a positive integer")
            event = save_event(
                {
                    "id": next_event_id(),
                    "title": title,
                    "day": day,
                    "attendees": list(payload.get("attendees", [])),
                    "cancelled": False,
                    "room": None,
                }
            )
            return created(serialize_event(event))
            """,
        ),
        _View(
            "reschedule_event_view",
            ("event_id", "payload"),
            """
            event = load_event(event_id)
            if event is None:
                return not_found("event", event_id)
            if event["cancelled"]:
                return conflict(f"event {event_id} is cancelled")
            day = payload.get("day")
            if not isinstance(day, int) or day < 1:
                return bad_request("day must be a positive integer")
            event["day"] = day
            return ok(serialize_event(save_event(event)))
            """,
        ),
        _View(
            "cancel_event_view",
            ("event_id",),
            """
            event = load_event(event_id)
            if event is None:
                return not_found("event", event_id)
            if event["cancelled"]:
                return conflict(f"event {event_id} is already cancelled")
            event["cancelled"] = True
            return ok(serialize_event(save_event(event)))
            """,
        ),
        _View(
            "restore_event_view",
            ("event_id",),
            """
            event = load_event(event_id)
            if event is None:
                return not_found("event", event_id)
            if not event["cancelled"]:
                return conflict(f"event {event_id} is not cancelled")
            event["cancelled"] = False
            return ok(serialize_event(save_event(event)))
            """,
        ),
        _View(
            "add_attendee_view",
            ("event_id", "payload"),
            """
            event = load_event(event_id)
            if event is None:
                return not_found("event", event_id)
            if event["cancelled"]:
                return conflict(f"event {event_id} is cancelled")
            name = str(payload.get("name", "")).strip()
            if not name:
                return bad_request("name is required")
            if name in event["attendees"]:
                return conflict(f"{name} is already attending")
            event["attendees"] = [*event["attendees"], name]
            return ok(serialize_event(save_event(event)))
            """,
        ),
        _View(
            "remove_attendee_view",
            ("event_id", "payload"),
            """
            event = load_event(event_id)
            if event is None:
                return not_found("event", event_id)
            name = str(payload.get("name", "")).strip()
            if name not in event["attendees"]:
                return not_found("attendee", name)
            event["attendees"] = [a for a in event["attendees"] if a != name]
            return ok(serialize_event(save_event(event)))
            """,
        ),
        _View(
            "clear_attendees_view",
            ("event_id",),
            """
            event = load_event(event_id)
            if event is None:
                return not_found("event", event_id)
            event["attendees"] = []
            return ok(serialize_event(save_event(event)))
            """,
        ),
    ),
    _View(
        "rename_event_view",
        ("event_id", "payload"),
        """
        event = load_event(event_id)
        if event is None:
            return not_found("event", event_id)
        if event["cancelled"]:
            return conflict(f"event {event_id} is cancelled")
        title = str(payload.get("title", "")).strip()
        if not title:
            return bad_request("title is required")
        if len(title) > MAX_TITLE:
            return bad_request(f"title must be at most {MAX_TITLE} characters")
        event["title"] = title
        return ok(serialize_event(save_event(event)))
        """,
    ),
    constants="MAX_TITLE = 60\n",
    docstring="HTTP routes for the calendar API.",
    distractor="""
        def settings_route(request):
            return ok({"timezone": "UTC"})
    """,
)


# task id -> (shared files, target file renderer, replacement helper file or None)
_SUBJECTS: dict[str, tuple[dict[str, str], _Target, tuple[str, str] | None]] = {
    "ticket-close": (_HELPDESK, _TICKET_ROUTES, ("src/helpdesk/views.py", _HELPDESK_VIEWS)),
    "book-return": (_LIBRARY, _BOOK_ROUTES, ("src/library/views.py", _LIBRARY_VIEWS)),
    "stock-reserve": (
        _INVENTORY,
        _PRODUCT_ROUTES,
        ("src/inventory/views.py", _INVENTORY_VIEWS),
    ),
    "event-rename": (_CALENDAR, _EVENT_ROUTES, ("src/calendar_api/views.py", _CALENDAR_VIEWS)),
    "free-shipping": (_STOREFRONT, _SHIPPING, None),
    "net-pay-dollars": (_PAYROLL, _NET_PAY, None),
    "parcel-quote-rounded": (_PARCELS, _PARCEL, None),
    "renewal-budget": (_BILLING, _RENEWAL, None),
    "email-key": (_ACCOUNTS, _EMAIL, None),
    "sku-key": (_CATALOG, _SKU, None),
    "sample-count": (_TELEMETRY, _COUNT, None),
    "postal-prefix": (_ADDRESSES, _POSTAL, None),
}


def _dose_task(task: CodingTask) -> CodingTask:
    replacement = _SUBJECTS[task.id][2]
    return (
        task if replacement is None else task.model_copy(update={"helper_source": replacement[1]})
    )


DOSE_TASKS: tuple[CodingTask, ...] = tuple(_dose_task(task) for task in LAYERED_TASKS)


def dose_repository_variants() -> dict[str, dict[str, dict[str, str]]]:
    """Every subject at every mess level; only the target file differs between arms."""
    variants: dict[str, dict[str, dict[str, str]]] = {}
    for task in DOSE_TASKS:
        shared, target, replacement = _SUBJECTS[task.id]
        files = dict(shared)
        if replacement is not None:
            files[replacement[0]] = replacement[1]
        variants[task.id] = {
            f"mess-{level:02d}": {**files, task.target_path: target.render(level)}
            for level in MESS_POSITIONS
        }
    return variants
