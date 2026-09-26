"""Dependency-light catalogue loading and content-addressed versioning."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from assay.canonical import canonical_json


class _CatalogueLoader(yaml.SafeLoader):
    """YAML 1.2-style booleans: question criteria keys ``true``/``false`` stay strings."""


_CatalogueLoader.yaml_implicit_resolvers = {
    key: [item for item in values if item[0] != "tag:yaml.org,2002:bool"]
    for key, values in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


@dataclass(frozen=True, slots=True)
class Catalogue:
    path: Path
    document: dict[str, Any]
    version: str

    @property
    def id(self) -> str:
        return str(self.document["id"])

    @property
    def decide(self) -> str:
        return str(self.document["decide"])

    @property
    def questions(self) -> dict[str, dict[str, Any]]:
        return dict(self.document["questions"])


class MalformedCatalogueError(ValueError):
    """A catalogue whose questions must not be dispatched to a provider or a reviewer."""


def _null_paths(value: Any, path: str) -> list[str]:
    if value is None:
        return [path]
    if isinstance(value, dict):
        return [
            found for key, child in value.items() for found in _null_paths(child, f"{path}.{key}")
        ]
    if isinstance(value, list):
        return [
            found
            for index, child in enumerate(value)
            for found in _null_paths(child, f"{path}[{index}]")
        ]
    return []


def check_dispatchable(questions: Mapping[str, Any]) -> None:
    """Refuse questions carrying a null anywhere, before they are dispatched.

    An unquoted YAML flow mapping such as ``{what: A product, vendor, or
    company.}`` loads as ``{"what": "A product", "vendor": None, ...}``: the
    commas split the criterion into null-valued keys. v1 was written that way
    and is kept loadable only so recorded runs still verify; it must not run.
    """
    nulls = [found for key, question in questions.items() for found in _null_paths(question, key)]
    if nulls:
        raise MalformedCatalogueError(
            f"{len(nulls)} null value(s) in catalogue questions, first {nulls[0]!r}; "
            "quote criteria text that contains commas"
        )


def load_catalogue(path: str | Path) -> Catalogue:
    catalogue_path = Path(path)
    document = yaml.load(catalogue_path.read_text(encoding="utf-8"), Loader=_CatalogueLoader)
    if not isinstance(document, dict):
        raise ValueError("catalogue must be an object")
    for key in ("id", "decide", "description", "state", "questions"):
        if key not in document:
            raise ValueError(f"catalogue is missing {key}")
    questions = document["questions"]
    if not isinstance(questions, dict) or not questions:
        raise ValueError("catalogue questions must be a non-empty object")
    version = hashlib.sha256(canonical_json(document)).hexdigest()
    return Catalogue(path=catalogue_path, document=document, version=version)
