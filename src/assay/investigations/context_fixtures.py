# ruff: noqa: E501
"""Context-size DRY scenarios: does a bigger codebase weaken consistency?

Every arm starts from the ``tail-07`` placement file (seven of ten existing
callers inline, clustered above the insertion point) and adds unrelated
support modules to the package until the repository reaches about 30 KB
(``ctx-30``) or 90 KB (``ctx-90``); ``ctx-00`` is unpadded. The target file,
the helper and its callers are identical across arms; only the amount of
surrounding code changes. Padding modules never mention the helper or the
target file.
"""

from __future__ import annotations

from textwrap import dedent

from assay.investigations.dose_fixtures import (
    DOSE_TASKS,
    PLACEMENT_LAYOUT,
    dose_repository_variants,
)

# Arm -> total repository bytes to pad up to (0 = unpadded).
CONTEXT_TARGETS = {"ctx-00": 0, "ctx-30": 30_000, "ctx-90": 90_000}
CONTEXT_ARMS = tuple(CONTEXT_TARGETS)

_AREAS = (
    "orders",
    "accounts",
    "catalog",
    "reports",
    "integrations",
    "notifications",
    "billing_ops",
    "search",
    "imports",
    "scheduling",
    "exports",
    "support",
    "pricing_admin",
    "fulfilment",
    "loyalty",
    "compliance",
)

_TEMPLATES: dict[str, str] = {
    "cache": '''
        """In-process TTL cache for NOUN lookups."""

        import time

        DEFAULT_TTL_SECONDS = 300
        _entries = {}


        def cache_key(*parts):
            return "NOUN:" + ":".join(str(part) for part in parts)


        def get_cached(key, now=None):
            now = time.monotonic() if now is None else now
            entry = _entries.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if expires_at <= now:
                _entries.pop(key, None)
                return None
            return value


        def put_cached(key, value, ttl=DEFAULT_TTL_SECONDS, now=None):
            now = time.monotonic() if now is None else now
            _entries[key] = (value, now + ttl)
            return value


        def invalidate(prefix):
            removed = [key for key in _entries if key.startswith(prefix)]
            for key in removed:
                del _entries[key]
            return len(removed)
    ''',
    "pagination": '''
        """Cursor and offset pagination helpers for NOUN listings."""

        DEFAULT_PAGE_SIZE = 25
        MAX_PAGE_SIZE = 200


        def clamp_page_size(requested):
            if requested is None:
                return DEFAULT_PAGE_SIZE
            return max(1, min(int(requested), MAX_PAGE_SIZE))


        def page_bounds(page, page_size):
            page = max(1, int(page))
            start = (page - 1) * page_size
            return start, start + page_size


        def paginate(items, page=1, page_size=None):
            size = clamp_page_size(page_size)
            start, end = page_bounds(page, size)
            window = list(items)[start:end]
            return {
                "items": window,
                "page": max(1, int(page)),
                "page_size": size,
                "has_more": end < len(list(items)),
            }


        def next_cursor(items, key="id"):
            if not items:
                return None
            return str(items[-1][key])
    ''',
    "retry": '''
        """Retry policy for outbound NOUN calls."""

        import random

        MAX_ATTEMPTS = 4
        BASE_DELAY_SECONDS = 0.2
        RETRYABLE_STATUSES = frozenset({429, 502, 503, 504})


        def backoff_delay(attempt, jitter=True):
            delay = BASE_DELAY_SECONDS * (2 ** max(0, attempt - 1))
            if jitter:
                delay *= 0.5 + random.random() / 2
            return round(delay, 3)


        def should_retry(status, attempt):
            return status in RETRYABLE_STATUSES and attempt < MAX_ATTEMPTS


        def retry_plan(statuses):
            plan = []
            for attempt, status in enumerate(statuses, start=1):
                if not should_retry(status, attempt):
                    break
                plan.append({"attempt": attempt, "status": status, "delay": backoff_delay(attempt, False)})
            return plan
    ''',
    "feature_flags": '''
        """Feature flags for the NOUN area, evaluated per tenant."""

        import hashlib

        FLAGS = {
            "NOUN_new_layout": {"enabled": True, "rollout_percent": 25},
            "NOUN_bulk_actions": {"enabled": True, "rollout_percent": 100},
            "NOUN_legacy_export": {"enabled": False, "rollout_percent": 0},
        }


        def _bucket(tenant, flag):
            digest = hashlib.sha256(f"{flag}:{tenant}".encode()).hexdigest()
            return int(digest[:8], 16) % 100


        def is_enabled(flag, tenant):
            config = FLAGS.get(flag)
            if config is None or not config["enabled"]:
                return False
            return _bucket(tenant, flag) < config["rollout_percent"]


        def enabled_flags(tenant):
            return sorted(flag for flag in FLAGS if is_enabled(flag, tenant))
    ''',
    "audit_log": '''
        """Append-only audit trail for NOUN changes."""

        _EVENTS = []


        def record(actor, action, target, detail=None):
            event = {
                "seq": len(_EVENTS) + 1,
                "actor": actor,
                "action": action,
                "target": target,
                "detail": dict(detail or {}),
            }
            _EVENTS.append(event)
            return event


        def events_for(target):
            return [event for event in _EVENTS if event["target"] == target]


        def actions_by(actor):
            counts = {}
            for event in _EVENTS:
                if event["actor"] == actor:
                    counts[event["action"]] = counts.get(event["action"], 0) + 1
            return counts


        def since(seq):
            return [event for event in _EVENTS if event["seq"] > seq]
    ''',
    "rate_limit": '''
        """Token-bucket rate limiting for NOUN API clients."""

        CAPACITY = 60
        REFILL_PER_SECOND = 1.0
        _buckets = {}


        def _refill(bucket, now):
            elapsed = max(0.0, now - bucket["updated"])
            bucket["tokens"] = min(CAPACITY, bucket["tokens"] + elapsed * REFILL_PER_SECOND)
            bucket["updated"] = now


        def allow(client, now, cost=1):
            bucket = _buckets.setdefault(client, {"tokens": CAPACITY, "updated": now})
            _refill(bucket, now)
            if bucket["tokens"] < cost:
                return False
            bucket["tokens"] -= cost
            return True


        def remaining(client, now):
            bucket = _buckets.get(client)
            if bucket is None:
                return CAPACITY
            _refill(bucket, now)
            return int(bucket["tokens"])
    ''',
    "dates": '''
        """Business-day arithmetic used by NOUN schedules."""

        from datetime import date, timedelta

        HOLIDAYS = frozenset({date(2026, 1, 1), date(2026, 12, 25), date(2026, 12, 26)})


        def is_business_day(day):
            return day.weekday() < 5 and day not in HOLIDAYS


        def add_business_days(start, count):
            day = start
            remaining = count
            while remaining > 0:
                day += timedelta(days=1)
                if is_business_day(day):
                    remaining -= 1
            return day


        def business_days_between(start, end):
            if end < start:
                start, end = end, start
            days = 0
            day = start
            while day < end:
                day += timedelta(days=1)
                if is_business_day(day):
                    days += 1
            return days
    ''',
    "csv_export": '''
        """CSV export of NOUN records for finance and support teams."""

        import csv
        import io

        COLUMNS = ("id", "created", "status", "owner")


        def to_row(record):
            return [str(record.get(column, "")) for column in COLUMNS]


        def export(records, columns=COLUMNS):
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(columns)
            for record in records:
                writer.writerow([str(record.get(column, "")) for column in columns])
            return buffer.getvalue()


        def parse(text):
            reader = csv.DictReader(io.StringIO(text))
            return [dict(row) for row in reader]
    ''',
    "permissions": '''
        """Role-based permissions for the NOUN area."""

        ROLE_GRANTS = {
            "viewer": {"read"},
            "editor": {"read", "write"},
            "admin": {"read", "write", "delete", "manage"},
        }


        def grants(roles):
            allowed = set()
            for role in roles:
                allowed |= ROLE_GRANTS.get(role, set())
            return allowed


        def can(user, action):
            return action in grants(user.get("roles", ()))


        def require(user, action):
            if not can(user, action):
                raise PermissionError(f"{user.get('id')} may not {action} NOUN")
            return True
    ''',
    "metrics": '''
        """Counters and timers for NOUN operations."""

        _counters = {}
        _timings = {}


        def increment(name, amount=1, **tags):
            key = (name, tuple(sorted(tags.items())))
            _counters[key] = _counters.get(key, 0) + amount
            return _counters[key]


        def observe(name, seconds):
            _timings.setdefault(name, []).append(seconds)


        def percentile(name, fraction):
            values = sorted(_timings.get(name, ()))
            if not values:
                return None
            index = min(len(values) - 1, int(fraction * len(values)))
            return values[index]


        def snapshot():
            return {
                "counters": {f"{name}{dict(tags)}": value for (name, tags), value in _counters.items()},
                "timings": {name: len(values) for name, values in _timings.items()},
            }
    ''',
    "webhooks": '''
        """Outbound webhook signing and delivery bookkeeping for NOUN events."""

        import hashlib
        import hmac
        import json

        _deliveries = []


        def sign(secret, body):
            payload = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
            return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


        def queue_delivery(url, event, secret):
            delivery = {"url": url, "event": event, "signature": sign(secret, event), "attempts": 0}
            _deliveries.append(delivery)
            return delivery


        def pending(max_attempts=5):
            return [delivery for delivery in _deliveries if delivery["attempts"] < max_attempts]


        def mark_attempt(delivery, succeeded):
            delivery["attempts"] += 1
            delivery["delivered"] = succeeded
            return delivery
    ''',
    "config": '''
        """Environment-driven configuration for the NOUN service."""

        import os

        DEFAULTS = {
            "NOUN_PAGE_SIZE": "25",
            "NOUN_TIMEOUT_SECONDS": "5",
            "NOUN_REGION": "eu-west-1",
            "NOUN_DEBUG": "0",
        }


        def setting(name, environ=None):
            environ = os.environ if environ is None else environ
            return environ.get(name, DEFAULTS.get(name))


        def int_setting(name, environ=None):
            value = setting(name, environ)
            return int(value) if value is not None else None


        def flag_setting(name, environ=None):
            return setting(name, environ) in {"1", "true", "yes"}


        def summary(environ=None):
            return {name: setting(name, environ) for name in sorted(DEFAULTS)}
    ''',
}


def _module(template: str, area: str) -> str:
    return dedent(template).strip("\n").replace("NOUN", area) + "\n"


def _padding(package: str, existing: dict[str, str], extra_bytes: int) -> dict[str, str]:
    """Support modules under ``src/<package>/<area>/`` totalling at least ``extra_bytes``."""
    files: dict[str, str] = {}
    added = 0
    for area in _AREAS:
        if added >= extra_bytes:
            break
        if f"src/{package}/{area}.py" in existing:
            continue  # a package directory would shadow the existing module
        init = f"src/{package}/{area}/__init__.py"
        files[init] = f'"""Support code for {area.replace("_", " ")}."""\n'
        for name, template in _TEMPLATES.items():
            if added >= extra_bytes:
                break
            path = f"src/{package}/{area}/{name}.py"
            if path in existing:
                continue
            files[path] = _module(template, area)
            added += len(files[path].encode())
    if added < extra_bytes:
        raise ValueError(f"not enough padding templates for {package}")
    return files


def context_repository_variants() -> dict[str, dict[str, dict[str, str]]]:
    """The ``tail-07`` file in repositories padded to about 30 KB and 90 KB."""
    base = dose_repository_variants({"tail-07": PLACEMENT_LAYOUT["tail-07"]})
    variants: dict[str, dict[str, dict[str, str]]] = {}
    for task in DOSE_TASKS:
        repository = base[task.id]["tail-07"]
        size = sum(len(content.encode()) for content in repository.values())
        package = task.target_path.split("/")[1]
        variants[task.id] = {
            arm: {**repository, **_padding(package, repository, max(0, target - size))}
            for arm, target in CONTEXT_TARGETS.items()
        }
    return variants
