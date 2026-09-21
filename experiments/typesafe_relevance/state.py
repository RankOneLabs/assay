"""Pure state projection shared by the study and Scout adoption."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def build_state(record: Mapping[str, Any], project: Mapping[str, str]) -> dict[str, Any]:
    parent = None
    if record.get("parent_author_name") is not None or record.get("parent_text") is not None:
        parent = {
            "author_name": record.get("parent_author_name"),
            "text": record.get("parent_text"),
        }
    return {
        "post": {
            "platform": record["platform"],
            "channel": record.get("channel"),
            "url": record.get("url"),
            "text": record.get("text"),
        },
        "parent_context_only": parent,
        "author": {
            "name": record.get("author_name"),
            "handle": record.get("author_handle"),
        },
        "project": {
            "key": project["key"],
            "name": project["name"],
            "description": project["description"],
        },
    }
