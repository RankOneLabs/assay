"""Multi-file DRY scenarios where the reusable unit lives outside the target file.

Three families, four subjects each:

* ``route-view``: routes either delegate to views or inline the view logic;
  the task adds the route for a view that exists but is not routed yet.
* ``domain-rule``: callers either use a composite business rule or recompose
  it from its building blocks; the task needs the composite's result.
* ``cross-module``: callers either import a value helper from ``utils.py`` or
  inline its expression; the task needs the same transformation.

Within a subject only the target file differs between arms, and in every arm
the target file already imports something from sibling modules,
so the arm manipulates how existing code reaches the behaviour, not whether
the package's layering is visible.
"""

from __future__ import annotations

from textwrap import dedent
from typing import Any

from assay.investigations.consistency import CodingTask, FunctionalCase


def _source(text: str) -> str:
    return dedent(text).lstrip("\n")


def _cases(*values: tuple[Any, Any]) -> tuple[FunctionalCase, ...]:
    return tuple(FunctionalCase(input=given, expected=expected) for given, expected in values)


_RESPONSES = _source(
    '''
    """Response envelopes shared by every route and view."""


    def ok(body):
        return {"status": 200, "body": body}


    def created(body):
        return {"status": 201, "body": body}


    def bad_request(message):
        return {"status": 400, "body": {"error": message}}


    def not_found(kind, identifier):
        return {"status": 404, "body": {"error": f"{kind} {identifier} not found"}}


    def conflict(message):
        return {"status": 409, "body": {"error": message}}
    '''
)


def _ok(body: Any) -> dict[str, Any]:
    return {"status": 200, "body": body}


def _error(status: int, message: str) -> dict[str, Any]:
    return {"status": status, "body": {"error": message}}


# --- route-view ----------------------------------------------------------------

_HELPDESK = {
    "src/helpdesk/__init__.py": '"""Helpdesk ticket service."""\n',
    "src/helpdesk/responses.py": _RESPONSES,
    "src/helpdesk/store.py": _source(
        '''
        """In-memory ticket storage seeded with fixtures."""

        _TICKETS = {
            1: {
                "id": 1,
                "subject": "Printer offline",
                "status": "open",
                "assignee": "dana",
                "priority": "high",
                "internal_notes": "toner reordered",
            },
            2: {
                "id": 2,
                "subject": "VPN drops hourly",
                "status": "open",
                "assignee": None,
                "priority": "normal",
                "internal_notes": "",
            },
            3: {
                "id": 3,
                "subject": "Password reset",
                "status": "closed",
                "assignee": "lee",
                "priority": "low",
                "internal_notes": "self-service link sent",
            },
        }


        def list_tickets():
            return [dict(ticket) for _, ticket in sorted(_TICKETS.items())]


        def load_ticket(ticket_id):
            ticket = _TICKETS.get(ticket_id)
            return None if ticket is None else dict(ticket)


        def save_ticket(ticket):
            _TICKETS[ticket["id"]] = dict(ticket)
            return dict(ticket)


        def next_ticket_id():
            return max(_TICKETS, default=0) + 1
        '''
    ),
    "src/helpdesk/serializers.py": _source(
        '''
        """Public ticket representation; internal notes never leave the service."""


        def serialize_ticket(ticket):
            return {
                "id": ticket["id"],
                "subject": ticket["subject"],
                "status": ticket["status"],
                "assignee": ticket["assignee"],
                "priority": ticket["priority"],
            }
        '''
    ),
    "src/helpdesk/views.py": _source(
        '''
        """Ticket views: each takes plain arguments and returns a response envelope."""

        from helpdesk.responses import bad_request, conflict, created, not_found, ok
        from helpdesk.serializers import serialize_ticket
        from helpdesk.store import list_tickets, load_ticket, next_ticket_id, save_ticket

        PRIORITIES = ("low", "normal", "high")


        def list_tickets_view():
            return ok([serialize_ticket(ticket) for ticket in list_tickets()])


        def get_ticket_view(ticket_id):
            ticket = load_ticket(ticket_id)
            if ticket is None:
                return not_found("ticket", ticket_id)
            return ok(serialize_ticket(ticket))


        def create_ticket_view(payload):
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


        def assign_ticket_view(ticket_id, payload):
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


        def close_ticket_view(ticket_id):
            ticket = load_ticket(ticket_id)
            if ticket is None:
                return not_found("ticket", ticket_id)
            if ticket["status"] == "closed":
                return conflict(f"ticket {ticket_id} is already closed")
            ticket["status"] = "closed"
            return ok(serialize_ticket(save_ticket(ticket)))
        '''
    ),
}

_HELPDESK_ROUTES_CLEAN = _source(
    '''
    """HTTP routes for the ticket API."""

    from helpdesk.responses import ok
    from helpdesk.views import (
        assign_ticket_view,
        create_ticket_view,
        get_ticket_view,
        list_tickets_view,
    )

    API_VERSION = "2024-06"


    def health_route(request):
        return ok({"status": "up", "version": API_VERSION})


    def list_tickets_route(request):
        return list_tickets_view()


    def get_ticket_route(request):
        return get_ticket_view(request["id"])


    def create_ticket_route(request):
        return create_ticket_view(request["body"])


    def assign_ticket_route(request):
        return assign_ticket_view(request["id"], request["body"])
    '''
)

_HELPDESK_ROUTES_INCONSISTENT = _source(
    '''
    """HTTP routes for the ticket API."""

    from helpdesk.responses import bad_request, conflict, created, not_found, ok
    from helpdesk.serializers import serialize_ticket
    from helpdesk.store import list_tickets, load_ticket, next_ticket_id, save_ticket
    from helpdesk.views import PRIORITIES

    API_VERSION = "2024-06"


    def health_route(request):
        return ok({"status": "up", "version": API_VERSION})


    def list_tickets_route(request):
        return ok([serialize_ticket(ticket) for ticket in list_tickets()])


    def get_ticket_route(request):
        ticket = load_ticket(request["id"])
        if ticket is None:
            return not_found("ticket", request["id"])
        return ok(serialize_ticket(ticket))


    def create_ticket_route(request):
        payload = request["body"]
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


    def assign_ticket_route(request):
        ticket = load_ticket(request["id"])
        if ticket is None:
            return not_found("ticket", request["id"])
        if ticket["status"] == "closed":
            return conflict(f"ticket {request['id']} is closed")
        assignee = str(request["body"].get("assignee", "")).strip()
        if not assignee:
            return bad_request("assignee is required")
        ticket["assignee"] = assignee
        return ok(serialize_ticket(save_ticket(ticket)))
    '''
)

_LIBRARY = {
    "src/library/__init__.py": '"""Branch library lending service."""\n',
    "src/library/responses.py": _RESPONSES,
    "src/library/store.py": _source(
        '''
        """In-memory catalogue seeded with fixtures."""

        _BOOKS = {
            1: {
                "id": 1,
                "title": "Dune",
                "author": "Frank Herbert",
                "borrower": "mo",
                "due_day": 12,
                "acquired": 2019,
            },
            2: {
                "id": 2,
                "title": "Emma",
                "author": "Jane Austen",
                "borrower": None,
                "due_day": None,
                "acquired": 2021,
            },
            3: {
                "id": 3,
                "title": "Ubik",
                "author": "Philip K. Dick",
                "borrower": "ana",
                "due_day": 9,
                "acquired": 2020,
            },
        }


        def list_books():
            return [dict(book) for _, book in sorted(_BOOKS.items())]


        def load_book(book_id):
            book = _BOOKS.get(book_id)
            return None if book is None else dict(book)


        def save_book(book):
            _BOOKS[book["id"]] = dict(book)
            return dict(book)


        def next_book_id():
            return max(_BOOKS, default=0) + 1
        '''
    ),
    "src/library/serializers.py": _source(
        '''
        """Public book representation; acquisition data stays internal."""


        def serialize_book(book):
            return {
                "id": book["id"],
                "title": book["title"],
                "author": book["author"],
                "available": book["borrower"] is None,
                "due_day": book["due_day"],
            }
        '''
    ),
    "src/library/views.py": _source(
        '''
        """Book views: each takes plain arguments and returns a response envelope."""

        from library.responses import bad_request, conflict, created, not_found, ok
        from library.serializers import serialize_book
        from library.store import list_books, load_book, next_book_id, save_book

        LOAN_DAYS = 21


        def list_books_view():
            return ok([serialize_book(book) for book in list_books()])


        def get_book_view(book_id):
            book = load_book(book_id)
            if book is None:
                return not_found("book", book_id)
            return ok(serialize_book(book))


        def add_book_view(payload):
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


        def checkout_book_view(book_id, payload):
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


        def return_book_view(book_id):
            book = load_book(book_id)
            if book is None:
                return not_found("book", book_id)
            if book["borrower"] is None:
                return conflict(f"book {book_id} is not checked out")
            book["borrower"] = None
            book["due_day"] = None
            return ok(serialize_book(save_book(book)))
        '''
    ),
}

_LIBRARY_ROUTES_CLEAN = _source(
    '''
    """HTTP routes for the lending API."""

    from library.responses import ok
    from library.views import (
        add_book_view,
        checkout_book_view,
        get_book_view,
        list_books_view,
    )

    BRANCH = "riverside"


    def branch_route(request):
        return ok({"branch": BRANCH})


    def list_books_route(request):
        return list_books_view()


    def get_book_route(request):
        return get_book_view(request["id"])


    def add_book_route(request):
        return add_book_view(request["body"])


    def checkout_book_route(request):
        return checkout_book_view(request["id"], request["body"])
    '''
)

_LIBRARY_ROUTES_INCONSISTENT = _source(
    '''
    """HTTP routes for the lending API."""

    from library.responses import bad_request, conflict, created, not_found, ok
    from library.serializers import serialize_book
    from library.store import list_books, load_book, next_book_id, save_book
    from library.views import LOAN_DAYS

    BRANCH = "riverside"


    def branch_route(request):
        return ok({"branch": BRANCH})


    def list_books_route(request):
        return ok([serialize_book(book) for book in list_books()])


    def get_book_route(request):
        book = load_book(request["id"])
        if book is None:
            return not_found("book", request["id"])
        return ok(serialize_book(book))


    def add_book_route(request):
        payload = request["body"]
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


    def checkout_book_route(request):
        book = load_book(request["id"])
        if book is None:
            return not_found("book", request["id"])
        if book["borrower"] is not None:
            return conflict(f"book {request['id']} is already checked out")
        borrower = str(request["body"].get("borrower", "")).strip()
        if not borrower:
            return bad_request("borrower is required")
        day = request["body"].get("day")
        if not isinstance(day, int):
            return bad_request("day must be an integer")
        book["borrower"] = borrower
        book["due_day"] = day + LOAN_DAYS
        return ok(serialize_book(save_book(book)))
    '''
)

_INVENTORY = {
    "src/inventory/__init__.py": '"""Warehouse stock service."""\n',
    "src/inventory/responses.py": _RESPONSES,
    "src/inventory/store.py": _source(
        '''
        """In-memory product storage seeded with fixtures."""

        _PRODUCTS = {
            1: {
                "id": 1,
                "sku": "LMP-01",
                "name": "Desk lamp",
                "on_hand": 12,
                "reserved": 4,
                "supplier": "Lumen",
            },
            2: {
                "id": 2,
                "sku": "CBL-20",
                "name": "USB-C cable",
                "on_hand": 3,
                "reserved": 3,
                "supplier": "Wirecraft",
            },
            3: {
                "id": 3,
                "sku": "MUG-07",
                "name": "Enamel mug",
                "on_hand": 40,
                "reserved": 0,
                "supplier": "Kiln & Co",
            },
        }


        def list_products():
            return [dict(product) for _, product in sorted(_PRODUCTS.items())]


        def load_product(product_id):
            product = _PRODUCTS.get(product_id)
            return None if product is None else dict(product)


        def save_product(product):
            _PRODUCTS[product["id"]] = dict(product)
            return dict(product)


        def next_product_id():
            return max(_PRODUCTS, default=0) + 1
        '''
    ),
    "src/inventory/serializers.py": _source(
        '''
        """Public product representation; supplier data stays internal."""


        def serialize_product(product):
            return {
                "id": product["id"],
                "sku": product["sku"],
                "name": product["name"],
                "available": product["on_hand"] - product["reserved"],
            }
        '''
    ),
    "src/inventory/views.py": _source(
        '''
        """Product views: each takes plain arguments and returns a response envelope."""

        from inventory.responses import bad_request, conflict, created, not_found, ok
        from inventory.serializers import serialize_product
        from inventory.store import list_products, load_product, next_product_id, save_product


        def _positive_quantity(payload):
            quantity = payload.get("quantity")
            if not isinstance(quantity, int) or quantity < 1:
                return None
            return quantity


        def list_products_view():
            return ok([serialize_product(product) for product in list_products()])


        def get_product_view(product_id):
            product = load_product(product_id)
            if product is None:
                return not_found("product", product_id)
            return ok(serialize_product(product))


        def create_product_view(payload):
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


        def restock_product_view(product_id, payload):
            product = load_product(product_id)
            if product is None:
                return not_found("product", product_id)
            quantity = _positive_quantity(payload)
            if quantity is None:
                return bad_request("quantity must be a positive integer")
            product["on_hand"] += quantity
            return ok(serialize_product(save_product(product)))


        def reserve_stock_view(product_id, payload):
            product = load_product(product_id)
            if product is None:
                return not_found("product", product_id)
            quantity = _positive_quantity(payload)
            if quantity is None:
                return bad_request("quantity must be a positive integer")
            available = product["on_hand"] - product["reserved"]
            if quantity > available:
                return conflict(f"only {available} of {product['sku']} available")
            product["reserved"] += quantity
            return ok(serialize_product(save_product(product)))
        '''
    ),
}

_INVENTORY_ROUTES_CLEAN = _source(
    '''
    """HTTP routes for the stock API."""

    from inventory.responses import ok
    from inventory.views import (
        create_product_view,
        get_product_view,
        list_products_view,
        restock_product_view,
    )

    WAREHOUSE = "north"


    def warehouse_route(request):
        return ok({"warehouse": WAREHOUSE})


    def list_products_route(request):
        return list_products_view()


    def get_product_route(request):
        return get_product_view(request["id"])


    def create_product_route(request):
        return create_product_view(request["body"])


    def restock_product_route(request):
        return restock_product_view(request["id"], request["body"])
    '''
)

_INVENTORY_ROUTES_INCONSISTENT = _source(
    '''
    """HTTP routes for the stock API."""

    from inventory.responses import bad_request, created, not_found, ok
    from inventory.serializers import serialize_product
    from inventory.store import list_products, load_product, next_product_id, save_product

    WAREHOUSE = "north"


    def warehouse_route(request):
        return ok({"warehouse": WAREHOUSE})


    def list_products_route(request):
        return ok([serialize_product(product) for product in list_products()])


    def get_product_route(request):
        product = load_product(request["id"])
        if product is None:
            return not_found("product", request["id"])
        return ok(serialize_product(product))


    def create_product_route(request):
        payload = request["body"]
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


    def restock_product_route(request):
        product = load_product(request["id"])
        if product is None:
            return not_found("product", request["id"])
        quantity = request["body"].get("quantity")
        if not isinstance(quantity, int) or quantity < 1:
            return bad_request("quantity must be a positive integer")
        product["on_hand"] += quantity
        return ok(serialize_product(save_product(product)))
    '''
)

_CALENDAR = {
    "src/calendar_api/__init__.py": '"""Team calendar service."""\n',
    "src/calendar_api/responses.py": _RESPONSES,
    "src/calendar_api/store.py": _source(
        '''
        """In-memory event storage seeded with fixtures."""

        _EVENTS = {
            1: {
                "id": 1,
                "title": "Planning",
                "day": 3,
                "attendees": ["ana", "bo"],
                "cancelled": False,
                "room": "A",
            },
            2: {
                "id": 2,
                "title": "Retro",
                "day": 5,
                "attendees": ["cy"],
                "cancelled": True,
                "room": "B",
            },
            3: {
                "id": 3,
                "title": "Offsite",
                "day": 9,
                "attendees": [],
                "cancelled": False,
                "room": None,
            },
        }


        def list_events():
            return [dict(event) for _, event in sorted(_EVENTS.items())]


        def load_event(event_id):
            event = _EVENTS.get(event_id)
            return None if event is None else dict(event)


        def save_event(event):
            _EVENTS[event["id"]] = dict(event)
            return dict(event)


        def next_event_id():
            return max(_EVENTS, default=0) + 1
        '''
    ),
    "src/calendar_api/serializers.py": _source(
        '''
        """Public event representation; room bookings stay internal."""


        def serialize_event(event):
            return {
                "id": event["id"],
                "title": event["title"],
                "day": event["day"],
                "attendee_count": len(event["attendees"]),
                "cancelled": event["cancelled"],
            }
        '''
    ),
    "src/calendar_api/views.py": _source(
        '''
        """Event views: each takes plain arguments and returns a response envelope."""

        from calendar_api.responses import bad_request, conflict, created, not_found, ok
        from calendar_api.serializers import serialize_event
        from calendar_api.store import list_events, load_event, next_event_id, save_event

        MAX_TITLE = 60


        def _clean_title(payload):
            title = str(payload.get("title", "")).strip()
            if not title:
                return None, "title is required"
            if len(title) > MAX_TITLE:
                return None, f"title must be at most {MAX_TITLE} characters"
            return title, None


        def list_events_view():
            return ok([serialize_event(event) for event in list_events() if not event["cancelled"]])


        def get_event_view(event_id):
            event = load_event(event_id)
            if event is None:
                return not_found("event", event_id)
            return ok(serialize_event(event))


        def create_event_view(payload):
            title, error = _clean_title(payload)
            if error:
                return bad_request(error)
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


        def reschedule_event_view(event_id, payload):
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


        def rename_event_view(event_id, payload):
            event = load_event(event_id)
            if event is None:
                return not_found("event", event_id)
            if event["cancelled"]:
                return conflict(f"event {event_id} is cancelled")
            title, error = _clean_title(payload)
            if error:
                return bad_request(error)
            event["title"] = title
            return ok(serialize_event(save_event(event)))
        '''
    ),
}

_CALENDAR_ROUTES_CLEAN = _source(
    '''
    """HTTP routes for the calendar API."""

    from calendar_api.responses import ok
    from calendar_api.views import (
        create_event_view,
        get_event_view,
        list_events_view,
        reschedule_event_view,
    )

    TIMEZONE = "UTC"


    def settings_route(request):
        return ok({"timezone": TIMEZONE})


    def list_events_route(request):
        return list_events_view()


    def get_event_route(request):
        return get_event_view(request["id"])


    def create_event_route(request):
        return create_event_view(request["body"])


    def reschedule_event_route(request):
        return reschedule_event_view(request["id"], request["body"])
    '''
)

_CALENDAR_ROUTES_INCONSISTENT = _source(
    '''
    """HTTP routes for the calendar API."""

    from calendar_api.responses import bad_request, conflict, created, not_found, ok
    from calendar_api.serializers import serialize_event
    from calendar_api.store import list_events, load_event, next_event_id, save_event
    from calendar_api.views import MAX_TITLE

    TIMEZONE = "UTC"


    def settings_route(request):
        return ok({"timezone": TIMEZONE})


    def list_events_route(request):
        return ok([serialize_event(event) for event in list_events() if not event["cancelled"]])


    def get_event_route(request):
        event = load_event(request["id"])
        if event is None:
            return not_found("event", request["id"])
        return ok(serialize_event(event))


    def create_event_route(request):
        payload = request["body"]
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


    def reschedule_event_route(request):
        event = load_event(request["id"])
        if event is None:
            return not_found("event", request["id"])
        if event["cancelled"]:
            return conflict(f"event {request['id']} is cancelled")
        day = request["body"].get("day")
        if not isinstance(day, int) or day < 1:
            return bad_request("day must be a positive integer")
        event["day"] = day
        return ok(serialize_event(save_event(event)))
    '''
)

# --- domain-rule ---------------------------------------------------------------

_FORMATTING = _source(
    '''
    """Display formatting shared by reports."""


    def format_cents(cents):
        sign = "-" if cents < 0 else ""
        cents = abs(cents)
        return f"{sign}${cents // 100:,}.{cents % 100:02d}"
    '''
)

_STOREFRONT = {
    "src/storefront/__init__.py": '"""Online storefront back office."""\n',
    "src/storefront/formatting.py": _FORMATTING,
    "src/storefront/pricing.py": _source(
        '''
        """Order pricing rules. All amounts are integer cents."""

        TAX_RATE_PERCENT = 8
        MAX_DISCOUNT_CENTS = 5000
        COUPONS = {"SAVE10": 10, "SAVE25": 25}


        def line_amount(line):
            return line["unit_cents"] * line["quantity"]


        def discount_for(coupon, subtotal_cents):
            percent = COUPONS.get(coupon, 0)
            return min(subtotal_cents * percent // 100, MAX_DISCOUNT_CENTS)


        def tax_on(amount_cents):
            return (amount_cents * TAX_RATE_PERCENT + 50) // 100


        def order_total(order):
            subtotal = sum(line_amount(line) for line in order["lines"])
            discounted = subtotal - discount_for(order.get("coupon"), subtotal)
            return discounted + tax_on(discounted)
        '''
    ),
}

_STOREFRONT_REPORTS_CLEAN = _source(
    '''
    """Order reporting for finance and customer-service tooling."""

    from storefront.formatting import format_cents
    from storefront.pricing import order_total

    FREE_SHIPPING_THRESHOLD_CENTS = 5000
    REVIEW_THRESHOLD_CENTS = 250_000


    def invoice_line(order):
        return f"Order {order['id']}: {format_cents(order_total(order))}"


    def loyalty_points(order):
        return order_total(order) // 100


    def needs_manual_review(order):
        return order_total(order) > REVIEW_THRESHOLD_CENTS


    def item_count(order):
        return sum(line["quantity"] for line in order["lines"])
    '''
)

_STOREFRONT_REPORTS_INCONSISTENT = _source(
    '''
    """Order reporting for finance and customer-service tooling."""

    from storefront.formatting import format_cents
    from storefront.pricing import discount_for, line_amount, tax_on

    FREE_SHIPPING_THRESHOLD_CENTS = 5000
    REVIEW_THRESHOLD_CENTS = 250_000


    def invoice_line(order):
        subtotal = sum(line_amount(line) for line in order["lines"])
        discounted = subtotal - discount_for(order.get("coupon"), subtotal)
        total = discounted + tax_on(discounted)
        return f"Order {order['id']}: {format_cents(total)}"


    def loyalty_points(order):
        subtotal = sum(line_amount(line) for line in order["lines"])
        discounted = subtotal - discount_for(order.get("coupon"), subtotal)
        return (discounted + tax_on(discounted)) // 100


    def needs_manual_review(order):
        subtotal = sum(line_amount(line) for line in order["lines"])
        discounted = subtotal - discount_for(order.get("coupon"), subtotal)
        return discounted + tax_on(discounted) > REVIEW_THRESHOLD_CENTS


    def item_count(order):
        return sum(line["quantity"] for line in order["lines"])
    '''
)

_PAYROLL = {
    "src/payroll/__init__.py": '"""Payroll processing."""\n',
    "src/payroll/formatting.py": _FORMATTING,
    "src/payroll/rules.py": _source(
        '''
        """Pay rules. All amounts are integer cents; hours are whole hours."""

        OVERTIME_THRESHOLD_HOURS = 40
        OVERTIME_MULTIPLIER_PERCENT = 150
        WITHHOLDING_BRACKETS = ((100_000, 10), (250_000, 20))
        TOP_WITHHOLDING_PERCENT = 30
        BENEFIT_PLAN_CENTS = {"basic": 2500, "family": 6000}


        def gross_pay(hours, rate_cents):
            regular = min(hours, OVERTIME_THRESHOLD_HOURS)
            overtime = max(hours - OVERTIME_THRESHOLD_HOURS, 0)
            overtime_rate = rate_cents * OVERTIME_MULTIPLIER_PERCENT // 100
            return regular * rate_cents + overtime * overtime_rate


        def withholding(gross_cents):
            for ceiling, percent in WITHHOLDING_BRACKETS:
                if gross_cents <= ceiling:
                    return gross_cents * percent // 100
            return gross_cents * TOP_WITHHOLDING_PERCENT // 100


        def benefit_deduction(plan):
            return BENEFIT_PLAN_CENTS.get(plan, 0)


        def net_pay(timesheet):
            gross = gross_pay(timesheet["hours"], timesheet["rate_cents"])
            return gross - withholding(gross) - benefit_deduction(timesheet.get("plan"))
        '''
    ),
}

_PAYROLL_PAYSLIPS_CLEAN = _source(
    '''
    """Payslips and bank instructions for a pay period."""

    from payroll.formatting import format_cents
    from payroll.rules import OVERTIME_THRESHOLD_HOURS, net_pay

    MINIMUM_NET_CENTS = 40_000


    def payslip_line(timesheet):
        return f"{timesheet['employee']}: {format_cents(net_pay(timesheet))}"


    def deposit_instruction(timesheet):
        return {"employee": timesheet["employee"], "amount_cents": net_pay(timesheet)}


    def below_minimum(timesheet):
        return net_pay(timesheet) < MINIMUM_NET_CENTS


    def overtime_hours(timesheet):
        return max(timesheet["hours"] - OVERTIME_THRESHOLD_HOURS, 0)
    '''
)

_PAYROLL_PAYSLIPS_INCONSISTENT = _source(
    '''
    """Payslips and bank instructions for a pay period."""

    from payroll.formatting import format_cents
    from payroll.rules import (
        OVERTIME_THRESHOLD_HOURS,
        benefit_deduction,
        gross_pay,
        withholding,
    )

    MINIMUM_NET_CENTS = 40_000


    def payslip_line(timesheet):
        gross = gross_pay(timesheet["hours"], timesheet["rate_cents"])
        net = gross - withholding(gross) - benefit_deduction(timesheet.get("plan"))
        return f"{timesheet['employee']}: {format_cents(net)}"


    def deposit_instruction(timesheet):
        gross = gross_pay(timesheet["hours"], timesheet["rate_cents"])
        net = gross - withholding(gross) - benefit_deduction(timesheet.get("plan"))
        return {"employee": timesheet["employee"], "amount_cents": net}


    def below_minimum(timesheet):
        gross = gross_pay(timesheet["hours"], timesheet["rate_cents"])
        net = gross - withholding(gross) - benefit_deduction(timesheet.get("plan"))
        return net < MINIMUM_NET_CENTS


    def overtime_hours(timesheet):
        return max(timesheet["hours"] - OVERTIME_THRESHOLD_HOURS, 0)
    '''
)

_PARCELS = {
    "src/parcels/__init__.py": '"""Parcel dispatch."""\n',
    "src/parcels/formatting.py": _FORMATTING,
    "src/parcels/rates.py": _source(
        '''
        """Carrier rate card. Amounts are integer cents, weights are grams."""

        ZONE_BASE_CENTS = {"local": 500, "regional": 900, "national": 1400}
        FREE_WEIGHT_GRAMS = 1000
        WEIGHT_STEP_GRAMS = 500
        WEIGHT_STEP_CENTS = 150
        FUEL_SURCHARGE_PERCENT = 12


        def zone_rate(zone):
            return ZONE_BASE_CENTS[zone]


        def weight_surcharge(grams):
            excess = grams - FREE_WEIGHT_GRAMS
            steps = max(0, -(-excess // WEIGHT_STEP_GRAMS))
            return steps * WEIGHT_STEP_CENTS


        def fuel_surcharge(amount_cents):
            return amount_cents * FUEL_SURCHARGE_PERCENT // 100


        def parcel_quote(parcel):
            base = zone_rate(parcel["zone"]) + weight_surcharge(parcel["grams"])
            return base + fuel_surcharge(base)
        '''
    ),
}

_PARCELS_MANIFEST_CLEAN = _source(
    '''
    """Dispatch manifests, labels and customs paperwork."""

    from parcels.formatting import format_cents
    from parcels.rates import parcel_quote

    HEAVY_GRAMS = 20_000


    def label_line(parcel):
        return f"{parcel['tracking']} {parcel['zone']} {format_cents(parcel_quote(parcel))}"


    def batch_total(parcels):
        return sum(parcel_quote(parcel) for parcel in parcels)


    def customs_declaration(parcel):
        return {
            "tracking": parcel["tracking"],
            "contents": parcel.get("contents", "merchandise"),
            "shipping_cents": parcel_quote(parcel),
        }


    def is_heavy(parcel):
        return parcel["grams"] > HEAVY_GRAMS
    '''
)

_PARCELS_MANIFEST_INCONSISTENT = _source(
    '''
    """Dispatch manifests, labels and customs paperwork."""

    from parcels.formatting import format_cents
    from parcels.rates import fuel_surcharge, weight_surcharge, zone_rate

    HEAVY_GRAMS = 20_000


    def label_line(parcel):
        base = zone_rate(parcel["zone"]) + weight_surcharge(parcel["grams"])
        quote = base + fuel_surcharge(base)
        return f"{parcel['tracking']} {parcel['zone']} {format_cents(quote)}"


    def batch_total(parcels):
        total = 0
        for parcel in parcels:
            base = zone_rate(parcel["zone"]) + weight_surcharge(parcel["grams"])
            total += base + fuel_surcharge(base)
        return total


    def customs_declaration(parcel):
        base = zone_rate(parcel["zone"]) + weight_surcharge(parcel["grams"])
        return {
            "tracking": parcel["tracking"],
            "contents": parcel.get("contents", "merchandise"),
            "shipping_cents": base + fuel_surcharge(base),
        }


    def is_heavy(parcel):
        return parcel["grams"] > HEAVY_GRAMS
    '''
)

_BILLING = {
    "src/billing/__init__.py": '"""Subscription billing."""\n',
    "src/billing/formatting.py": _FORMATTING,
    "src/billing/plans.py": _source(
        '''
        """Subscription pricing. Amounts are integer cents per billing period."""

        PLAN_SEAT_CENTS = {"starter": 800, "team": 1500, "enterprise": 3000}
        VOLUME_TIERS = ((50, 20), (10, 10))
        ANNUAL_PREPAY_PERCENT = 85


        def seat_price(plan):
            return PLAN_SEAT_CENTS[plan]


        def volume_discount(seats, amount_cents):
            for minimum_seats, percent in VOLUME_TIERS:
                if seats >= minimum_seats:
                    return amount_cents * percent // 100
            return 0


        def annual_price(monthly_cents):
            return monthly_cents * 12 * ANNUAL_PREPAY_PERCENT // 100


        def renewal_amount(subscription):
            seats = subscription["seats"]
            amount = seat_price(subscription["plan"]) * seats
            amount -= volume_discount(seats, amount)
            if subscription.get("annual"):
                return annual_price(amount)
            return amount
        '''
    ),
}

_BILLING_RENEWALS_CLEAN = _source(
    '''
    """Renewal notices, invoice drafts and approval routing."""

    from billing.formatting import format_cents
    from billing.plans import PLAN_SEAT_CENTS, renewal_amount

    APPROVAL_LIMIT_CENTS = 500_000


    def renewal_notice(subscription):
        amount = renewal_amount(subscription)
        return f"{subscription['account']} renews at {format_cents(amount)}"


    def invoice_draft(subscription):
        return {
            "account": subscription["account"],
            "amount_cents": renewal_amount(subscription),
            "annual": bool(subscription.get("annual")),
        }


    def requires_approval(subscription):
        return renewal_amount(subscription) > APPROVAL_LIMIT_CENTS


    def is_known_plan(subscription):
        return subscription["plan"] in PLAN_SEAT_CENTS
    '''
)

_BILLING_RENEWALS_INCONSISTENT = _source(
    '''
    """Renewal notices, invoice drafts and approval routing."""

    from billing.formatting import format_cents
    from billing.plans import PLAN_SEAT_CENTS, annual_price, seat_price, volume_discount

    APPROVAL_LIMIT_CENTS = 500_000


    def renewal_notice(subscription):
        seats = subscription["seats"]
        amount = seat_price(subscription["plan"]) * seats
        amount -= volume_discount(seats, amount)
        if subscription.get("annual"):
            amount = annual_price(amount)
        return f"{subscription['account']} renews at {format_cents(amount)}"


    def invoice_draft(subscription):
        seats = subscription["seats"]
        amount = seat_price(subscription["plan"]) * seats
        amount -= volume_discount(seats, amount)
        if subscription.get("annual"):
            amount = annual_price(amount)
        return {
            "account": subscription["account"],
            "amount_cents": amount,
            "annual": bool(subscription.get("annual")),
        }


    def requires_approval(subscription):
        seats = subscription["seats"]
        amount = seat_price(subscription["plan"]) * seats
        amount -= volume_discount(seats, amount)
        if subscription.get("annual"):
            amount = annual_price(amount)
        return amount > APPROVAL_LIMIT_CENTS


    def is_known_plan(subscription):
        return subscription["plan"] in PLAN_SEAT_CENTS
    '''
)

# --- cross-module --------------------------------------------------------------

_ACCOUNTS = {
    "src/accounts/__init__.py": '"""Account signup and identity."""\n',
    "src/accounts/utils.py": _source(
        '''
        """Small string helpers shared across the accounts service."""


        def normalize_email(value):
            return value.strip().lower()


        def email_domain(value):
            return value.rsplit("@", 1)[-1]


        def mask_email(value):
            local, _, domain = value.partition("@")
            return f"{local[:1]}***@{domain}"


        def slugify(value):
            return "-".join(value.lower().split())
        '''
    ),
    "src/accounts/audit.py": _source(
        '''
        """Audit trail entries for identity changes."""

        from accounts.utils import email_domain


        def signup_event(payload):
            return {"kind": "signup", "domain": email_domain(payload["email"])}
        '''
    ),
}

_ACCOUNTS_HANDLERS_CLEAN = _source(
    '''
    """Request handlers for signup, invitations and account merging."""

    from accounts.utils import mask_email, normalize_email

    MAX_DISPLAY_NAME = 40


    def signup_key(payload):
        return normalize_email(payload["email"])


    def invite_key(invite):
        return normalize_email(invite["address"])


    def same_account(pair):
        return normalize_email(pair["first"]) == normalize_email(pair["second"])


    def confirmation_notice(payload):
        return f"We sent a link to {mask_email(payload['email'])}"


    def display_name(payload):
        return payload.get("name", "")[:MAX_DISPLAY_NAME]
    '''
)

_ACCOUNTS_HANDLERS_INCONSISTENT = _source(
    '''
    """Request handlers for signup, invitations and account merging."""

    from accounts.utils import mask_email

    MAX_DISPLAY_NAME = 40


    def signup_key(payload):
        return payload["email"].strip().lower()


    def invite_key(invite):
        return invite["address"].strip().lower()


    def same_account(pair):
        return pair["first"].strip().lower() == pair["second"].strip().lower()


    def confirmation_notice(payload):
        return f"We sent a link to {mask_email(payload['email'])}"


    def display_name(payload):
        return payload.get("name", "")[:MAX_DISPLAY_NAME]
    '''
)

_CATALOG = {
    "src/catalog/__init__.py": '"""Product catalogue."""\n',
    "src/catalog/utils.py": _source(
        '''
        """Formatting helpers shared across the catalogue."""


        def canonical_sku(value):
            return value.strip().upper().replace(" ", "-")


        def price_label(cents):
            return f"${cents // 100}.{cents % 100:02d}"


        def truncate(value, width):
            return value if len(value) <= width else value[: width - 1] + "…"


        def title_case(value):
            return " ".join(word.capitalize() for word in value.split())
        '''
    ),
    "src/catalog/feeds.py": _source(
        '''
        """Partner feed rows."""

        from catalog.utils import price_label, title_case


        def feed_row(product):
            return [title_case(product["name"]), price_label(product["price_cents"])]
        '''
    ),
}

_CATALOG_HANDLERS_CLEAN = _source(
    '''
    """Handlers for imports, API lookups and listing pages."""

    from catalog.utils import canonical_sku, truncate

    LISTING_TITLE_WIDTH = 32


    def import_row_sku(row):
        return canonical_sku(row["sku"])


    def api_lookup_key(request):
        return canonical_sku(request["query"]["sku"])


    def same_sku(pair):
        return canonical_sku(pair["first"]) == canonical_sku(pair["second"])


    def listing_title(product):
        return truncate(product["name"], LISTING_TITLE_WIDTH)
    '''
)

_CATALOG_HANDLERS_INCONSISTENT = _source(
    '''
    """Handlers for imports, API lookups and listing pages."""

    from catalog.utils import truncate

    LISTING_TITLE_WIDTH = 32


    def import_row_sku(row):
        return row["sku"].strip().upper().replace(" ", "-")


    def api_lookup_key(request):
        return request["query"]["sku"].strip().upper().replace(" ", "-")


    def same_sku(pair):
        first = pair["first"].strip().upper().replace(" ", "-")
        return first == pair["second"].strip().upper().replace(" ", "-")


    def listing_title(product):
        return truncate(product["name"], LISTING_TITLE_WIDTH)
    '''
)

_TELEMETRY = {
    "src/telemetry/__init__.py": '"""Metrics ingestion."""\n',
    "src/telemetry/utils.py": _source(
        '''
        """Parsing helpers for raw metric payloads."""


        def parse_count(value):
            return max(0, int(value.strip()))


        def parse_ratio(value):
            return float(value.strip())


        def format_rate(count, seconds):
            return f"{count / seconds:.2f}/s"


        def bucket_label(metric):
            return metric.split(".", 1)[0]
        '''
    ),
    "src/telemetry/dashboards.py": _source(
        '''
        """Dashboard tiles."""

        from telemetry.utils import bucket_label, format_rate


        def rate_tile(metric, count, seconds):
            return {"group": bucket_label(metric), "rate": format_rate(count, seconds)}
        '''
    ),
}

_TELEMETRY_HANDLERS_CLEAN = _source(
    '''
    """Handlers for incoming metric samples."""

    from telemetry.utils import parse_count, parse_ratio

    IDLE_RATIO = 0.05


    def ingest_sample(sample):
        return {"metric": sample["metric"], "count": parse_count(sample["count"])}


    def merge_counts(pair):
        return parse_count(pair["first"]) + parse_count(pair["second"])


    def is_idle(sample):
        return parse_count(sample["count"]) == 0


    def is_saturated(sample):
        return parse_ratio(sample["utilisation"]) > 1 - IDLE_RATIO
    '''
)

_TELEMETRY_HANDLERS_INCONSISTENT = _source(
    '''
    """Handlers for incoming metric samples."""

    from telemetry.utils import parse_ratio

    IDLE_RATIO = 0.05


    def ingest_sample(sample):
        return {"metric": sample["metric"], "count": max(0, int(sample["count"].strip()))}


    def merge_counts(pair):
        return max(0, int(pair["first"].strip())) + max(0, int(pair["second"].strip()))


    def is_idle(sample):
        return max(0, int(sample["count"].strip())) == 0


    def is_saturated(sample):
        return parse_ratio(sample["utilisation"]) > 1 - IDLE_RATIO
    '''
)

_ADDRESSES = {
    "src/addresses/__init__.py": '"""Postal address handling."""\n',
    "src/addresses/utils.py": _source(
        '''
        """Postcode and country helpers."""

        COUNTRIES = {"GB": "United Kingdom", "IE": "Ireland"}


        def postal_prefix(value):
            return value.replace(" ", "").upper()[:3]


        def format_postcode(value):
            return value.strip().upper()


        def country_name(code):
            return COUNTRIES.get(code, code)
        '''
    ),
    "src/addresses/labels.py": _source(
        '''
        """Printable address labels."""

        from addresses.utils import country_name, format_postcode


        def label_lines(address):
            return [
                address["street"],
                format_postcode(address["postcode"]),
                country_name(address["country"]),
            ]
        '''
    ),
}

_ADDRESSES_HANDLERS_CLEAN = _source(
    '''
    """Handlers for sorting and routing addresses."""

    from addresses.utils import country_name, postal_prefix


    def sorting_bin(address):
        return postal_prefix(address["postcode"])


    def same_district(pair):
        return postal_prefix(pair["first"]) == postal_prefix(pair["second"])


    def route_key(address):
        return f"{address['country']}-{postal_prefix(address['postcode'])}"


    def destination(address):
        return country_name(address["country"])
    '''
)

_ADDRESSES_HANDLERS_INCONSISTENT = _source(
    '''
    """Handlers for sorting and routing addresses."""

    from addresses.utils import country_name


    def sorting_bin(address):
        return address["postcode"].replace(" ", "").upper()[:3]


    def same_district(pair):
        first = pair["first"].replace(" ", "").upper()[:3]
        return first == pair["second"].replace(" ", "").upper()[:3]


    def route_key(address):
        return f"{address['country']}-{address['postcode'].replace(' ', '').upper()[:3]}"


    def destination(address):
        return country_name(address["country"])
    '''
)


def _task(
    *,
    id: str,
    family: str,
    target_path: str,
    helper_path: str,
    shared: dict[str, str],
    instruction: str,
    helper: str,
    primitives: tuple[str, ...],
    test_cases: tuple[FunctionalCase, ...],
    reused_source: str,
    duplicated_source: str,
) -> CodingTask:
    helper_module = ".".join(helper_path.removeprefix("src/").removesuffix(".py").split("/"))
    return CodingTask(
        id=id,
        family=family,  # type: ignore[arg-type]
        instruction=f"In {target_path}, add {instruction}",
        helper=helper,
        primitives=primitives,
        helper_source=shared[helper_path],
        target_path=target_path,
        helper_module=helper_module,
        test_cases=test_cases,
        reused_source=_source(reused_source),
        duplicated_source=_source(duplicated_source),
    )


_FIXTURES: tuple[tuple[CodingTask, dict[str, str], str, str], ...] = (
    (
        _task(
            id="ticket-close",
            family="route-view",
            target_path="src/helpdesk/routes.py",
            helper_path="src/helpdesk/views.py",
            shared=_HELPDESK,
            instruction=(
                'implement(request), the route that closes the ticket whose id is request["id"].'
            ),
            helper="close_ticket_view",
            primitives=("load_ticket", "save_ticket", "serialize_ticket"),
            test_cases=_cases(
                (
                    {"id": 1},
                    _ok(
                        {
                            "id": 1,
                            "subject": "Printer offline",
                            "status": "closed",
                            "assignee": "dana",
                            "priority": "high",
                        }
                    ),
                ),
                ({"id": 3}, _error(409, "ticket 3 is already closed")),
                ({"id": 42}, _error(404, "ticket 42 not found")),
            ),
            reused_source="""
                from helpdesk.views import close_ticket_view


                def implement(request):
                    return close_ticket_view(request["id"])
            """,
            duplicated_source="""
                from helpdesk.responses import conflict, not_found, ok
                from helpdesk.serializers import serialize_ticket
                from helpdesk.store import load_ticket, save_ticket


                def implement(request):
                    ticket = load_ticket(request["id"])
                    if ticket is None:
                        return not_found("ticket", request["id"])
                    if ticket["status"] == "closed":
                        return conflict(f"ticket {request['id']} is already closed")
                    ticket["status"] = "closed"
                    return ok(serialize_ticket(save_ticket(ticket)))
            """,
        ),
        _HELPDESK,
        _HELPDESK_ROUTES_CLEAN,
        _HELPDESK_ROUTES_INCONSISTENT,
    ),
    (
        _task(
            id="book-return",
            family="route-view",
            target_path="src/library/routes.py",
            helper_path="src/library/views.py",
            shared=_LIBRARY,
            instruction=(
                "implement(request), the route that checks in a returned book whose id is "
                'request["id"].'
            ),
            helper="return_book_view",
            primitives=("load_book", "save_book", "serialize_book"),
            test_cases=_cases(
                (
                    {"id": 1},
                    _ok(
                        {
                            "id": 1,
                            "title": "Dune",
                            "author": "Frank Herbert",
                            "available": True,
                            "due_day": None,
                        }
                    ),
                ),
                ({"id": 2}, _error(409, "book 2 is not checked out")),
                ({"id": 7}, _error(404, "book 7 not found")),
            ),
            reused_source="""
                from library.views import return_book_view


                def implement(request):
                    return return_book_view(request["id"])
            """,
            duplicated_source="""
                from library.responses import conflict, not_found, ok
                from library.serializers import serialize_book
                from library.store import load_book, save_book


                def implement(request):
                    book = load_book(request["id"])
                    if book is None:
                        return not_found("book", request["id"])
                    if book["borrower"] is None:
                        return conflict(f"book {request['id']} is not checked out")
                    book["borrower"] = None
                    book["due_day"] = None
                    return ok(serialize_book(save_book(book)))
            """,
        ),
        _LIBRARY,
        _LIBRARY_ROUTES_CLEAN,
        _LIBRARY_ROUTES_INCONSISTENT,
    ),
    (
        _task(
            id="stock-reserve",
            family="route-view",
            target_path="src/inventory/routes.py",
            helper_path="src/inventory/views.py",
            shared=_INVENTORY,
            instruction=(
                'implement(request), the route that reserves request["body"]["quantity"] units '
                'of the product whose id is request["id"].'
            ),
            helper="reserve_stock_view",
            primitives=("load_product", "save_product", "serialize_product"),
            test_cases=_cases(
                (
                    {"id": 1, "body": {"quantity": 5}},
                    _ok({"id": 1, "sku": "LMP-01", "name": "Desk lamp", "available": 3}),
                ),
                ({"id": 2, "body": {"quantity": 1}}, _error(409, "only 0 of CBL-20 available")),
                (
                    {"id": 3, "body": {"quantity": 0}},
                    _error(400, "quantity must be a positive integer"),
                ),
                ({"id": 9, "body": {"quantity": 1}}, _error(404, "product 9 not found")),
            ),
            reused_source="""
                from inventory.views import reserve_stock_view


                def implement(request):
                    return reserve_stock_view(request["id"], request["body"])
            """,
            duplicated_source="""
                from inventory.responses import bad_request, conflict, not_found, ok
                from inventory.serializers import serialize_product
                from inventory.store import load_product, save_product


                def implement(request):
                    product = load_product(request["id"])
                    if product is None:
                        return not_found("product", request["id"])
                    quantity = request["body"].get("quantity")
                    if not isinstance(quantity, int) or quantity < 1:
                        return bad_request("quantity must be a positive integer")
                    available = product["on_hand"] - product["reserved"]
                    if quantity > available:
                        return conflict(f"only {available} of {product['sku']} available")
                    product["reserved"] += quantity
                    return ok(serialize_product(save_product(product)))
            """,
        ),
        _INVENTORY,
        _INVENTORY_ROUTES_CLEAN,
        _INVENTORY_ROUTES_INCONSISTENT,
    ),
    (
        _task(
            id="event-rename",
            family="route-view",
            target_path="src/calendar_api/routes.py",
            helper_path="src/calendar_api/views.py",
            shared=_CALENDAR,
            instruction=(
                'implement(request), the route that renames the event whose id is request["id"] '
                'to request["body"]["title"].'
            ),
            helper="rename_event_view",
            primitives=("load_event", "save_event", "serialize_event"),
            test_cases=_cases(
                (
                    {"id": 1, "body": {"title": "  Quarterly planning "}},
                    _ok(
                        {
                            "id": 1,
                            "title": "Quarterly planning",
                            "day": 3,
                            "attendee_count": 2,
                            "cancelled": False,
                        }
                    ),
                ),
                ({"id": 2, "body": {"title": "Retro"}}, _error(409, "event 2 is cancelled")),
                ({"id": 3, "body": {"title": "   "}}, _error(400, "title is required")),
                ({"id": 8, "body": {"title": "Standup"}}, _error(404, "event 8 not found")),
            ),
            reused_source="""
                from calendar_api.views import rename_event_view


                def implement(request):
                    return rename_event_view(request["id"], request["body"])
            """,
            duplicated_source="""
                from calendar_api.responses import bad_request, conflict, not_found, ok
                from calendar_api.serializers import serialize_event
                from calendar_api.store import load_event, save_event
                from calendar_api.views import MAX_TITLE


                def implement(request):
                    event = load_event(request["id"])
                    if event is None:
                        return not_found("event", request["id"])
                    if event["cancelled"]:
                        return conflict(f"event {request['id']} is cancelled")
                    title = str(request["body"].get("title", "")).strip()
                    if not title:
                        return bad_request("title is required")
                    if len(title) > MAX_TITLE:
                        return bad_request(f"title must be at most {MAX_TITLE} characters")
                    event["title"] = title
                    return ok(serialize_event(save_event(event)))
            """,
        ),
        _CALENDAR,
        _CALENDAR_ROUTES_CLEAN,
        _CALENDAR_ROUTES_INCONSISTENT,
    ),
    (
        _task(
            id="free-shipping",
            family="domain-rule",
            target_path="src/storefront/reports.py",
            helper_path="src/storefront/pricing.py",
            shared=_STOREFRONT,
            instruction=(
                "implement(order) returning whether the order total qualifies for free "
                "shipping (at least FREE_SHIPPING_THRESHOLD_CENTS)."
            ),
            helper="order_total",
            primitives=("line_amount", "discount_for", "tax_on"),
            test_cases=_cases(
                (
                    {
                        "id": "A-1",
                        "lines": [{"sku": "MUG-07", "unit_cents": 2350, "quantity": 2}],
                        "coupon": None,
                    },
                    True,
                ),
                (
                    {
                        "id": "A-2",
                        "lines": [{"sku": "LMP-01", "unit_cents": 3000, "quantity": 2}],
                        "coupon": "SAVE25",
                    },
                    False,
                ),
                (
                    {
                        "id": "A-3",
                        "lines": [
                            {"sku": "CBL-20", "unit_cents": 1000, "quantity": 3},
                            {"sku": "MUG-07", "unit_cents": 1200, "quantity": 1},
                        ],
                        "coupon": "SAVE10",
                    },
                    False,
                ),
            ),
            reused_source="""
                from storefront.pricing import order_total


                def implement(order):
                    return order_total(order) >= FREE_SHIPPING_THRESHOLD_CENTS
            """,
            duplicated_source="""
                from storefront.pricing import discount_for, line_amount, tax_on


                def implement(order):
                    subtotal = sum(line_amount(line) for line in order["lines"])
                    discounted = subtotal - discount_for(order.get("coupon"), subtotal)
                    total = discounted + tax_on(discounted)
                    return total >= FREE_SHIPPING_THRESHOLD_CENTS
            """,
        ),
        _STOREFRONT,
        _STOREFRONT_REPORTS_CLEAN,
        _STOREFRONT_REPORTS_INCONSISTENT,
    ),
    (
        _task(
            id="net-pay-dollars",
            family="domain-rule",
            target_path="src/payroll/payslips.py",
            helper_path="src/payroll/rules.py",
            shared=_PAYROLL,
            instruction=(
                "implement(timesheet) returning the employee's net pay in whole dollars, "
                "rounded down."
            ),
            helper="net_pay",
            primitives=("gross_pay", "withholding", "benefit_deduction"),
            test_cases=_cases(
                ({"employee": "ana", "hours": 38, "rate_cents": 2500, "plan": "basic"}, 830),
                ({"employee": "bo", "hours": 45, "rate_cents": 3000, "plan": "family"}, 1080),
                ({"employee": "cy", "hours": 10, "rate_cents": 1999, "plan": None}, 179),
            ),
            reused_source="""
                from payroll.rules import net_pay


                def implement(timesheet):
                    return net_pay(timesheet) // 100
            """,
            duplicated_source="""
                from payroll.rules import benefit_deduction, gross_pay, withholding


                def implement(timesheet):
                    gross = gross_pay(timesheet["hours"], timesheet["rate_cents"])
                    net = gross - withholding(gross) - benefit_deduction(timesheet.get("plan"))
                    return net // 100
            """,
        ),
        _PAYROLL,
        _PAYROLL_PAYSLIPS_CLEAN,
        _PAYROLL_PAYSLIPS_INCONSISTENT,
    ),
    (
        _task(
            id="parcel-quote-rounded",
            family="domain-rule",
            target_path="src/parcels/manifest.py",
            helper_path="src/parcels/rates.py",
            shared=_PARCELS,
            instruction=(
                "implement(parcel) returning the parcel's shipping quote rounded up to a whole "
                "dollar, in cents."
            ),
            helper="parcel_quote",
            primitives=("zone_rate", "weight_surcharge", "fuel_surcharge"),
            test_cases=_cases(
                ({"tracking": "P1", "zone": "local", "grams": 900}, 600),
                ({"tracking": "P2", "zone": "national", "grams": 2300}, 2100),
                ({"tracking": "P3", "zone": "regional", "grams": 1500}, 1200),
            ),
            reused_source="""
                from parcels.rates import parcel_quote


                def implement(parcel):
                    return -(-parcel_quote(parcel) // 100) * 100
            """,
            duplicated_source="""
                from parcels.rates import fuel_surcharge, weight_surcharge, zone_rate


                def implement(parcel):
                    base = zone_rate(parcel["zone"]) + weight_surcharge(parcel["grams"])
                    quote = base + fuel_surcharge(base)
                    return -(-quote // 100) * 100
            """,
        ),
        _PARCELS,
        _PARCELS_MANIFEST_CLEAN,
        _PARCELS_MANIFEST_INCONSISTENT,
    ),
    (
        _task(
            id="renewal-budget",
            family="domain-rule",
            target_path="src/billing/renewals.py",
            helper_path="src/billing/plans.py",
            shared=_BILLING,
            instruction=(
                "implement(subscription) returning whether the renewal amount is within "
                'subscription["budget_cents"].'
            ),
            helper="renewal_amount",
            primitives=("seat_price", "volume_discount", "annual_price"),
            test_cases=_cases(
                (
                    {
                        "account": "acme",
                        "plan": "team",
                        "seats": 12,
                        "annual": False,
                        "budget_cents": 17_000,
                    },
                    True,
                ),
                (
                    {
                        "account": "globex",
                        "plan": "starter",
                        "seats": 5,
                        "annual": True,
                        "budget_cents": 40_000,
                    },
                    False,
                ),
                (
                    {
                        "account": "initech",
                        "plan": "enterprise",
                        "seats": 60,
                        "annual": False,
                        "budget_cents": 150_000,
                    },
                    True,
                ),
            ),
            reused_source="""
                from billing.plans import renewal_amount


                def implement(subscription):
                    return renewal_amount(subscription) <= subscription["budget_cents"]
            """,
            duplicated_source="""
                from billing.plans import annual_price, seat_price, volume_discount


                def implement(subscription):
                    seats = subscription["seats"]
                    amount = seat_price(subscription["plan"]) * seats
                    amount -= volume_discount(seats, amount)
                    if subscription.get("annual"):
                        amount = annual_price(amount)
                    return amount <= subscription["budget_cents"]
            """,
        ),
        _BILLING,
        _BILLING_RENEWALS_CLEAN,
        _BILLING_RENEWALS_INCONSISTENT,
    ),
    (
        _task(
            id="email-key",
            family="cross-module",
            target_path="src/accounts/handlers.py",
            helper_path="src/accounts/utils.py",
            shared=_ACCOUNTS,
            instruction=(
                'implement(payload) returning payload["email"] with surrounding whitespace '
                "removed and lowercased."
            ),
            helper="normalize_email",
            primitives=("strip", "lower"),
            test_cases=_cases(
                ({"email": "  Ana@Example.COM "}, "ana@example.com"),
                ({"email": "BO@x.io"}, "bo@x.io"),
                ({"email": ""}, ""),
            ),
            reused_source="""
                from accounts.utils import normalize_email


                def implement(payload):
                    return normalize_email(payload["email"])
            """,
            duplicated_source="""
                def implement(payload):
                    return payload["email"].strip().lower()
            """,
        ),
        _ACCOUNTS,
        _ACCOUNTS_HANDLERS_CLEAN,
        _ACCOUNTS_HANDLERS_INCONSISTENT,
    ),
    (
        _task(
            id="sku-key",
            family="cross-module",
            target_path="src/catalog/handlers.py",
            helper_path="src/catalog/utils.py",
            shared=_CATALOG,
            instruction=(
                'implement(line) returning line["sku"] trimmed, uppercased, and with spaces '
                "replaced by hyphens."
            ),
            helper="canonical_sku",
            primitives=("strip", "upper", "replace"),
            test_cases=_cases(
                ({"sku": " ab 12 "}, "AB-12"),
                ({"sku": "x y z"}, "X-Y-Z"),
                ({"sku": "LMP-01"}, "LMP-01"),
            ),
            reused_source="""
                from catalog.utils import canonical_sku


                def implement(line):
                    return canonical_sku(line["sku"])
            """,
            duplicated_source="""
                def implement(line):
                    return line["sku"].strip().upper().replace(" ", "-")
            """,
        ),
        _CATALOG,
        _CATALOG_HANDLERS_CLEAN,
        _CATALOG_HANDLERS_INCONSISTENT,
    ),
    (
        _task(
            id="sample-count",
            family="cross-module",
            target_path="src/telemetry/handlers.py",
            helper_path="src/telemetry/utils.py",
            shared=_TELEMETRY,
            instruction=(
                'implement(sample) returning sample["count"] parsed as a trimmed base-10 '
                "integer, with negative counts floored at zero."
            ),
            helper="parse_count",
            primitives=("max", "int", "strip"),
            test_cases=_cases(
                ({"metric": "api.requests", "count": " 42 "}, 42),
                ({"metric": "api.errors", "count": "-5"}, 0),
                ({"metric": "db.reads", "count": "007"}, 7),
            ),
            reused_source="""
                from telemetry.utils import parse_count


                def implement(sample):
                    return parse_count(sample["count"])
            """,
            duplicated_source="""
                def implement(sample):
                    return max(0, int(sample["count"].strip()))
            """,
        ),
        _TELEMETRY,
        _TELEMETRY_HANDLERS_CLEAN,
        _TELEMETRY_HANDLERS_INCONSISTENT,
    ),
    (
        _task(
            id="postal-prefix",
            family="cross-module",
            target_path="src/addresses/handlers.py",
            helper_path="src/addresses/utils.py",
            shared=_ADDRESSES,
            instruction=(
                'implement(address) returning the first three characters of address["postcode"] '
                "after removing spaces and uppercasing."
            ),
            helper="postal_prefix",
            primitives=("replace", "upper"),
            test_cases=_cases(
                ({"postcode": "sw1a 1aa", "country": "GB"}, "SW1"),
                ({"postcode": "e 1 6an", "country": "GB"}, "E16"),
                ({"postcode": "d02", "country": "IE"}, "D02"),
            ),
            reused_source="""
                from addresses.utils import postal_prefix


                def implement(address):
                    return postal_prefix(address["postcode"])
            """,
            duplicated_source="""
                def implement(address):
                    return address["postcode"].replace(" ", "").upper()[:3]
            """,
        ),
        _ADDRESSES,
        _ADDRESSES_HANDLERS_CLEAN,
        _ADDRESSES_HANDLERS_INCONSISTENT,
    ),
)

LAYERED_TASKS: tuple[CodingTask, ...] = tuple(task for task, *_ in _FIXTURES)


def layered_repository_variants() -> dict[str, dict[str, dict[str, str]]]:
    """Both arms of every subject; only the target file differs between them."""
    return {
        task.id: {
            "clean": {**shared, task.target_path: clean},
            "inconsistent": {**shared, task.target_path: inconsistent},
        }
        for task, shared, clean, inconsistent in _FIXTURES
    }
