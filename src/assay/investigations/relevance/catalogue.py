"""Dependency-light catalogue loading and content-addressed versioning."""

from __future__ import annotations

import hashlib
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
