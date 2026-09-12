"""Deterministic, reviewable multi-file repositories for consistency pilots."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from assay.investigations.consistency import CodingTask, FunctionalCase
from assay.repository import validate_repository

ArmId = Literal["clean", "inconsistent"]


@dataclass(frozen=True, slots=True)
class RepositoryFixture:
    """One task and two repositories whose treatment is confined to one file."""

    id: str
    task: CodingTask
    target_path: str
    clean_repository: Mapping[str, str]
    inconsistent_repository: Mapping[str, str]

    def repository(self, arm: str) -> Mapping[str, str]:
        if arm == "clean":
            return self.clean_repository
        if arm == "inconsistent":
            return self.inconsistent_repository
        raise ValueError(f"unknown repository arm: {arm}")


@dataclass(frozen=True, slots=True)
class _Domain:
    id: str
    package: str
    title: str
    entities: tuple[str, ...]
    statuses: tuple[str, ...]
    helper: str
    primitives: tuple[str, ...]
    expression: str
    instruction_result: str
    family: Literal["cosmetic", "architectural", "semantic"]
    cases: tuple[FunctionalCase, ...]


def _lines(*parts: str) -> str:
    return "\n".join(part.rstrip("\n") for part in parts) + "\n"


def _init_module(domain: _Domain) -> str:
    exports = [f'    "{entity.title()}",' for entity in domain.entities]
    imports = [f"from .models.{entity} import {entity.title()}" for entity in domain.entities]
    return _lines(
        f'"""Public API for the {domain.title.lower()} package."""',
        "",
        *imports,
        "",
        "__all__ = [",
        *exports,
        "]",
    )


def _config_module(domain: _Domain) -> str:
    return _lines(
        f'"""Configuration primitives for {domain.title.lower()}."""',
        "",
        "from __future__ import annotations",
        "",
        "from dataclasses import dataclass",
        "from os import environ",
        "",
        "",
        "@dataclass(frozen=True, slots=True)",
        "class Settings:",
        "    environment: str = \"development\"",
        "    page_size: int = 100",
        "    audit_enabled: bool = True",
        "    request_timeout_seconds: float = 3.0",
        "",
        "    @classmethod",
        "    def from_environment(cls) -> Settings:",
        "        page_size = int(environ.get(\"APP_PAGE_SIZE\", \"100\"))",
        "        timeout = float(environ.get(\"APP_REQUEST_TIMEOUT\", \"3.0\"))",
        "        return cls(",
        "            environment=environ.get(\"APP_ENVIRONMENT\", \"development\"),",
        "            page_size=max(1, min(page_size, 500)),",
        "            audit_enabled=environ.get(\"APP_AUDIT_ENABLED\", \"1\") == \"1\",",
        "            request_timeout_seconds=max(0.1, timeout),",
        "        )",
        "",
        "",
        "DEFAULT_SETTINGS = Settings()",
    )


def _errors_module(domain: _Domain) -> str:
    classes = []
    for entity in domain.entities:
        title = entity.title()
        classes.extend(
            [
                "",
                "",
                f"class {title}NotFound(DomainError):",
                f'    """Raised when a requested {entity} does not exist."""',
                "",
                "",
                f"class Invalid{title}(DomainError):",
                f'    """Raised when {entity} data violates a domain invariant."""',
            ]
        )
    return _lines(
        f'"""Domain exceptions for {domain.title.lower()}."""',
        "",
        "",
        "class DomainError(Exception):",
        '    """Base class for errors safe to present at the service boundary."""',
        *classes,
    )


def _model_module(domain: _Domain, entity: str) -> str:
    title = entity.title()
    status_values = [f'    {status.upper()} = "{status}"' for status in domain.statuses]
    return _lines(
        f'"""{title} domain model."""',
        "",
        "from __future__ import annotations",
        "",
        "from dataclasses import dataclass, replace",
        "from datetime import UTC, datetime",
        "from enum import StrEnum",
        "from typing import Any, Mapping",
        "",
        "",
        f"class {title}Status(StrEnum):",
        *status_values,
        "",
        "",
        "def utc_now() -> datetime:",
        "    return datetime.now(UTC)",
        "",
        "",
        "@dataclass(frozen=True, slots=True)",
        f"class {title}:",
        "    id: str",
        "    name: str",
        f"    status: {title}Status",
        "    revision: int",
        "    created_at: datetime",
        "    updated_at: datetime",
        "    attributes: Mapping[str, str]",
        "",
        "    @classmethod",
        f"    def create(cls, *, id: str, name: str) -> {title}:",
        "        now = utc_now()",
        "        return cls(",
        "            id=id,",
        "            name=name,",
        f"            status={title}Status.{domain.statuses[0].upper()},",
        "            revision=1,",
        "            created_at=now,",
        "            updated_at=now,",
        "            attributes={},",
        "        )",
        "",
        f"    def rename(self, name: str) -> {title}:",
        "        return replace(self, name=name, revision=self.revision + 1, updated_at=utc_now())",
        "",
        f"    def transition(self, status: {title}Status) -> {title}:",
        "        return replace(",
        "            self, status=status, revision=self.revision + 1, updated_at=utc_now()",
        "        )",
        "",
        f"    def with_attribute(self, key: str, value: str) -> {title}:",
        "        attributes = dict(self.attributes)",
        "        attributes[key] = value",
        "        return replace(",
        "            self, attributes=attributes, revision=self.revision + 1, updated_at=utc_now()",
        "        )",
        "",
        "    def to_mapping(self) -> dict[str, Any]:",
        "        return {",
        '            "id": self.id,',
        '            "name": self.name,',
        '            "status": self.status.value,',
        '            "revision": self.revision,',
        '            "created_at": self.created_at.isoformat(),',
        '            "updated_at": self.updated_at.isoformat(),',
        '            "attributes": dict(sorted(self.attributes.items())),',
        "        }",
        "",
        "    @classmethod",
        f"    def from_mapping(cls, value: Mapping[str, Any]) -> {title}:",
        "        return cls(",
        '            id=str(value["id"]),',
        '            name=str(value["name"]),',
        f'            status={title}Status(str(value["status"])),',
        '            revision=int(value["revision"]),',
        '            created_at=datetime.fromisoformat(str(value["created_at"])),',
        '            updated_at=datetime.fromisoformat(str(value["updated_at"])),',
        '            attributes={str(k): str(v) for k, v in dict(value["attributes"]).items()},',
        "        )",
    )


def _repository_module(domain: _Domain, entity: str) -> str:
    title = entity.title()
    return _lines(
        f'"""Persistence ports and an in-memory {entity} adapter."""',
        "",
        "from __future__ import annotations",
        "",
        "from collections.abc import Iterable",
        "from typing import Protocol",
        "",
        f"from ..models.{entity} import {title}",
        "",
        "",
        f"class {title}Repository(Protocol):",
        f"    def get(self, {entity}_id: str) -> {title} | None: ...",
        "",
        f"    def save(self, value: {title}) -> None: ...",
        "",
        f"    def list(self, *, offset: int = 0, limit: int = 100) -> tuple[{title}, ...]: ...",
        "",
        f"    def delete(self, {entity}_id: str) -> bool: ...",
        "",
        "",
        f"class Memory{title}Repository:",
        f"    def __init__(self, values: Iterable[{title}] = ()) -> None:",
        f"        self._values: dict[str, {title}] = {{value.id: value for value in values}}",
        "",
        f"    def get(self, {entity}_id: str) -> {title} | None:",
        f"        return self._values.get({entity}_id)",
        "",
        f"    def save(self, value: {title}) -> None:",
        "        current = self._values.get(value.id)",
        "        if current is not None and current.revision >= value.revision:",
        '            raise ValueError("revision must increase")',
        "        self._values[value.id] = value",
        "",
        f"    def list(self, *, offset: int = 0, limit: int = 100) -> tuple[{title}, ...]:",
        "        ordered = sorted(self._values.values(), key=lambda value: value.id)",
        "        return tuple(ordered[offset : offset + limit])",
        "",
        f"    def delete(self, {entity}_id: str) -> bool:",
        f"        return self._values.pop({entity}_id, None) is not None",
        "",
        "    def count(self) -> int:",
        "        return len(self._values)",
        "",
        "    def clear(self) -> None:",
        "        self._values.clear()",
    )


def _validation_module(domain: _Domain, entity: str) -> str:
    title = entity.title()
    field_functions: list[str] = []
    for field in ("id", "name", "owner", "region", "source", "category"):
        field_functions.extend(
            [
                "",
                "",
                f"def validate_{field}(value: str) -> str:",
                "    cleaned = value.strip()",
                "    if not cleaned:",
                f'        raise Invalid{title}("{field} must not be blank")',
                "    if len(cleaned) > 200:",
                f'        raise Invalid{title}("{field} is too long")',
                "    return cleaned",
            ]
        )
    return _lines(
        f'"""Validation rules for {entity} commands."""',
        "",
        "from __future__ import annotations",
        "",
        f"from ..errors import Invalid{title}",
        *field_functions,
        "",
        "",
        "def validate_attributes(value: dict[str, str]) -> dict[str, str]:",
        "    if len(value) > 50:",
        f'        raise Invalid{title}("too many attributes")',
        "    return {validate_name(key): validate_name(item) for key, item in value.items()}",
    )


def _service_module(domain: _Domain, entity: str) -> str:
    title = entity.title()
    return _lines(
        f'"""Application service for {entity} workflows."""',
        "",
        "from __future__ import annotations",
        "",
        f"from ..errors import {title}NotFound",
        f"from ..models.{entity} import {title}, {title}Status",
        f"from ..repositories.{entity} import {title}Repository",
        f"from ..validation.{entity} import validate_id, validate_name",
        "",
        "",
        f"class {title}Service:",
        f"    def __init__(self, repository: {title}Repository) -> None:",
        "        self._repository = repository",
        "",
        f"    def create(self, *, {entity}_id: str, name: str) -> {title}:",
        f"        identifier = validate_id({entity}_id)",
        "        value = " + title + ".create(id=identifier, name=validate_name(name))",
        "        self._repository.save(value)",
        "        return value",
        "",
        f"    def require(self, {entity}_id: str) -> {title}:",
        f"        identifier = validate_id({entity}_id)",
        "        value = self._repository.get(identifier)",
        "        if value is None:",
        f"            raise {title}NotFound(identifier)",
        "        return value",
        "",
        f"    def rename(self, {entity}_id: str, name: str) -> {title}:",
        f"        value = self.require({entity}_id).rename(validate_name(name))",
        "        self._repository.save(value)",
        "        return value",
        "",
        f"    def transition(self, {entity}_id: str, status: {title}Status) -> {title}:",
        f"        value = self.require({entity}_id).transition(status)",
        "        self._repository.save(value)",
        "        return value",
        "",
        f"    def set_attribute(self, {entity}_id: str, key: str, value: str) -> {title}:",
        f"        current = self.require({entity}_id)",
        "        changed = current.with_attribute(validate_name(key), validate_name(value))",
        "        self._repository.save(changed)",
        "        return changed",
        "",
        f"    def delete(self, {entity}_id: str) -> bool:",
        f"        return self._repository.delete(validate_id({entity}_id))",
        "",
        f"    def list(self, *, offset: int = 0, limit: int = 100) -> tuple[{title}, ...]:",
        "        if offset < 0 or not 1 <= limit <= 500:",
        '            raise ValueError("invalid pagination")',
        "        return self._repository.list(offset=offset, limit=limit)",
    )


def _serialization_module(domain: _Domain, entity: str) -> str:
    title = entity.title()
    return _lines(
        f'"""JSON boundary helpers for {entity} values."""',
        "",
        "from __future__ import annotations",
        "",
        "import json",
        "from typing import Any",
        "",
        f"from ..models.{entity} import {title}",
        "",
        "",
        f"def encode_{entity}(value: {title}) -> str:",
        "    return json.dumps(",
        "        value.to_mapping(),",
        "        ensure_ascii=False,",
        "        allow_nan=False,",
        "        sort_keys=True,",
        '        separators=(",", ":"),',
        "    )",
        "",
        "",
        f"def decode_{entity}(value: str) -> {title}:",
        "    decoded: Any = json.loads(value)",
        "    if not isinstance(decoded, dict):",
        '        raise ValueError("expected an object")',
        f"    return {title}.from_mapping(decoded)",
        "",
        "",
        f"def encode_{entity}_list(values: tuple[{title}, ...]) -> str:",
        "    payload = [value.to_mapping() for value in values]",
        "    return json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True)",
        "",
        "",
        f"def decode_{entity}_list(value: str) -> tuple[{title}, ...]:",
        "    decoded: Any = json.loads(value)",
        "    if not isinstance(decoded, list):",
        '        raise ValueError("expected an array")',
        f"    return tuple({title}.from_mapping(item) for item in decoded)",
    )


def _normalization_module(domain: _Domain, *, clean: bool) -> str:
    existing = (
        f"{domain.helper}(value)" if clean else domain.expression
    )
    return _lines(
        f'"""Canonical input normalization for {domain.title.lower()}."""',
        "",
        "from __future__ import annotations",
        "",
        "",
        f"def {domain.helper}(value):",
        f"    return {domain.expression}",
        "",
        "",
        "def normalize_import_value(value):",
        f"    return {existing}",
        "",
        "",
        "def normalize_api_value(value):",
        f"    return {existing}",
        "",
        "",
        "def normalize_batch_value(value):",
        f"    return {existing}",
        "",
        "",
        "def normalize_optional_value(value):",
        "    return None if value is None else " + domain.helper + "(value)",
    )


def _build_repository(domain: _Domain, *, clean: bool) -> dict[str, str]:
    root = f"src/{domain.package}"
    repository = {
        "README.md": _lines(
            f"# {domain.title}",
            "",
            "A small service package with explicit domain, persistence, and application layers.",
            "All public mutations pass through validation and immutable domain models.",
        ),
        "pyproject.toml": _lines(
            "[project]",
            f'name = "{domain.package.replace("_", "-")}"',
            'version = "0.1.0"',
            'requires-python = ">=3.13"',
            "",
            "[tool.pytest.ini_options]",
            'testpaths = ["tests"]',
        ),
        f"{root}/__init__.py": _init_module(domain),
        f"{root}/config.py": _config_module(domain),
        f"{root}/errors.py": _errors_module(domain),
        f"{root}/normalization.py": _normalization_module(domain, clean=clean),
    }
    for namespace in ("models", "repositories", "serialization", "services", "validation"):
        repository[f"{root}/{namespace}/__init__.py"] = f'"""{namespace.title()} package."""\n'
    for entity in domain.entities:
        repository[f"{root}/models/{entity}.py"] = _model_module(domain, entity)
        repository[f"{root}/repositories/{entity}.py"] = _repository_module(domain, entity)
        repository[f"{root}/serialization/{entity}.py"] = _serialization_module(domain, entity)
        repository[f"{root}/services/{entity}.py"] = _service_module(domain, entity)
        repository[f"{root}/validation/{entity}.py"] = _validation_module(domain, entity)
    return repository


def _case(value: object, expected: object) -> FunctionalCase:
    return FunctionalCase(input=value, expected=expected)


_DOMAINS = (
    _Domain(
        id="commerce-sku",
        package="marketplace",
        title="Marketplace Operations",
        entities=("catalog", "inventory", "listing", "merchant"),
        statuses=("draft", "active", "archived"),
        helper="normalize_sku",
        primitives=("strip", "upper"),
        expression="value.strip().upper()",
        instruction_result="a SKU with surrounding whitespace removed and letters uppercased",
        family="cosmetic",
        cases=(_case(" ab-12 ", "AB-12"), _case("xYz", "XYZ"), _case("", "")),
    ),
    _Domain(
        id="support-tag",
        package="supportdesk",
        title="Support Desk",
        entities=("ticket", "queue", "agent", "conversation"),
        statuses=("new", "open", "closed"),
        helper="normalize_tag",
        primitives=("strip", "lower"),
        expression="value.strip().lower()",
        instruction_result=(
            "a support tag with surrounding whitespace removed and letters lowercased"
        ),
        family="cosmetic",
        cases=(_case(" Billing ", "billing"), _case("VIP", "vip"), _case("", "")),
    ),
    _Domain(
        id="telemetry-count",
        package="telemetryhub",
        title="Telemetry Hub",
        entities=("metric", "stream", "sample", "retention"),
        statuses=("pending", "enabled", "disabled"),
        helper="parse_sample_count",
        primitives=("max", "int"),
        expression="max(0, int(value))",
        instruction_result="a nonnegative integer sample count",
        family="semantic",
        cases=(_case("12", 12), _case("-7", 0), _case("0", 0)),
    ),
    _Domain(
        id="identity-name",
        package="identitysvc",
        title="Identity Service",
        entities=("account", "profile", "membership", "organization"),
        statuses=("invited", "active", "suspended"),
        helper="normalize_display_name",
        primitives=("strip", "title"),
        expression="value.strip().title()",
        instruction_result="a trimmed, title-cased display name",
        family="architectural",
        cases=(
            _case(" alice smith ", "Alice Smith"),
            _case("mARY-jANE", "Mary-Jane"),
            _case("", ""),
        ),
    ),
)


def _fixture(domain: _Domain) -> RepositoryFixture:
    clean = _build_repository(domain, clean=True)
    inconsistent = _build_repository(domain, clean=False)
    target_path = f"src/{domain.package}/normalization.py"
    task = CodingTask(
        id=domain.id,
        family=domain.family,
        instruction=(
            f"In {target_path}, add implement(value) returning {domain.instruction_result}."
        ),
        helper=domain.helper,
        primitives=domain.primitives,
        helper_source=clean[target_path],
        target_path=target_path,
        test_cases=domain.cases,
        reused_source=f"def implement(value):\n    return {domain.helper}(value)\n",
        duplicated_source=f"def implement(value):\n    return {domain.expression}\n",
    )
    return RepositoryFixture(
        id=domain.id,
        task=task,
        target_path=target_path,
        clean_repository=MappingProxyType(clean),
        inconsistent_repository=MappingProxyType(inconsistent),
    )


REALISTIC_PILOT_FIXTURES = tuple(_fixture(domain) for domain in _DOMAINS)
REALISTIC_PILOT_TASKS = tuple(fixture.task for fixture in REALISTIC_PILOT_FIXTURES)


def realistic_repository_variants() -> dict[str, dict[str, Mapping[str, str]]]:
    """Return the complete arm mapping consumed by consistency materialization."""
    return {
        fixture.task.id: {
            "clean": fixture.clean_repository,
            "inconsistent": fixture.inconsistent_repository,
        }
        for fixture in REALISTIC_PILOT_FIXTURES
    }


def repository_lines(repository: Mapping[str, str]) -> int:
    """Count physical lines in all text files exactly as sent to a model."""
    return sum(len(source.splitlines()) for source in repository.values())


def validate_repository_fixture(fixture: RepositoryFixture) -> None:
    """Fail closed if generation drifts outside the preregisterable fixture boundary."""
    clean = validate_repository(fixture.clean_repository)
    inconsistent = validate_repository(fixture.inconsistent_repository)
    if clean.keys() != inconsistent.keys() or fixture.target_path not in clean:
        raise ValueError("fixture arms must have identical trees and a shared target")
    for path, source in clean.items():
        if not source or not inconsistent[path]:
            raise ValueError(f"repository file must be nonempty text: {path}")
        if path.endswith(".py"):
            ast.parse(source, filename=path)
            ast.parse(inconsistent[path], filename=path)
    differing = [path for path in clean if clean[path] != inconsistent[path]]
    if differing != [fixture.target_path]:
        raise ValueError("treatment must be confined to the target module")
    for repository in (clean, inconsistent):
        lines = repository_lines(repository)
        if lines != 1_225:
            raise ValueError(f"repository must contain exactly 1,225 lines, got {lines}")
        if len(repository) < 20:
            raise ValueError("repository must contain at least twenty files")
    if fixture.task.helper not in clean[fixture.target_path]:
        raise ValueError("target module must define the governed helper")
    if (
        "def implement(" in clean[fixture.target_path]
        or "def implement(" in inconsistent[fixture.target_path]
    ):
        raise ValueError("fixture repositories must not contain the requested implementation")


for _generated_fixture in REALISTIC_PILOT_FIXTURES:
    validate_repository_fixture(_generated_fixture)
