"""Frozen operator inputs for a code extension launch.

The configuration is public evidence. Credentials are read by transports from
the environment and must never be put in this object.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from assay.canonical import canonical_json, digest_bytes
from code_extension.bridge import AUTHORIZED_MODEL_ROUTES
from code_extension.protocol import (
    ORDERED_TOOL_SCHEMAS_SHA256,
    SYSTEM_PROMPT_SHA256,
    surface_digests,
)
from code_extension.settings import ExtensionAgentSettings, UnauthorizedExtensionRoute


class RunConfigurationError(ValueError):
    """An operator input cannot define an authorized run."""


class MissingSpendCap(RunConfigurationError):
    """A positive attempt or run cap is required."""


class UnknownPricing(RunConfigurationError):
    """No conservative request bound can be established."""


class IdentityDrift(RunConfigurationError):
    """The supplied protocol or fixture identity differs from its pin."""


class SecretInConfiguration(RunConfigurationError):
    """Credentials may not be archived with the run configuration."""


class QualificationRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    scenario: str
    manifest_digest: str


class ModelRoute(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    endpoint: str
    model: str
    provider: str


class PricingAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    basis: str | None
    conservative_request_bound_usd: Decimal | None


class RunConfiguration(BaseModel):
    """All identity and monetary fields are mandatory and validated together."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    scenario_qualifications: tuple[QualificationRef, ...] = Field(min_length=1)
    cohort: str
    route: ModelRoute
    profile: str
    system_prompt_digest: str
    tool_schemas_digest: str
    image_digest: str
    bounds: ExtensionAgentSettings
    repeats: int = Field(ge=1, strict=True)
    randomization_seed: int = Field(strict=True)
    concurrency: int = Field(ge=1, strict=True)
    pricing: PricingAssumptions
    per_attempt_cap_usd: Decimal
    total_cap_usd: Decimal

    @model_validator(mode="before")
    @classmethod
    def reject_secrets(cls, value: Any) -> Any:
        if isinstance(value, dict):
            for name in ("per_attempt_cap_usd", "total_cap_usd"):
                if value.get(name) is None:
                    raise MissingSpendCap(f"MissingSpendCap: {name} is required")
            route = value.get("route")
            if not isinstance(route, dict) or any(
                not route.get(name) for name in ("endpoint", "model", "provider")
            ):
                raise RunConfigurationError(
                    "ExactRouteRequired: endpoint, model and provider are required"
                )

        def walk(item: Any) -> None:
            if isinstance(item, dict):
                for key, child in item.items():
                    if any(
                        word in key.lower()
                        for word in ("secret", "password", "api_key", "authorization")
                    ) or key.lower() in ("token", "access_token", "refresh_token"):
                        raise SecretInConfiguration(f"secret field in run configuration: {key}")
                    walk(child)
            elif isinstance(item, (list, tuple)):
                for child in item:
                    walk(child)
            elif isinstance(item, str) and ("Bearer " in item or "sk-" in item):
                raise SecretInConfiguration("credential value in run configuration")

        walk(value)
        return value

    @model_validator(mode="after")
    def validate_launch_identity(self) -> Self:
        if not self.cohort or not self.profile:
            raise RunConfigurationError("cohort and profile are required")
        if len({ref.scenario for ref in self.scenario_qualifications}) != len(
            self.scenario_qualifications
        ):
            raise RunConfigurationError("duplicate scenario qualification")
        if any(
            not ref.scenario or re.fullmatch(r"sha256:[0-9a-f]{64}", ref.manifest_digest) is None
            for ref in self.scenario_qualifications
        ):
            raise RunConfigurationError("invalid scenario qualification ref")
        route = (self.route.endpoint, self.route.model, self.route.provider)
        if route not in AUTHORIZED_MODEL_ROUTES:
            raise UnauthorizedExtensionRoute(f"unauthorized extension model route: {route}")
        if self.bounds != ExtensionAgentSettings.for_model(self.route.model):
            raise RunConfigurationError("bounds differ from qualified model envelope")
        if self.concurrency != 1:
            raise RunConfigurationError("extension concurrency must be one")
        if (
            self.system_prompt_digest != SYSTEM_PROMPT_SHA256
            or self.tool_schemas_digest != ORDERED_TOOL_SCHEMAS_SHA256
        ):
            raise IdentityDrift("prompt or tool identity differs from ce-v1")
        if (
            surface_digests()["system_prompt"] != SYSTEM_PROMPT_SHA256
            or surface_digests()["ordered_tool_schemas"] != ORDERED_TOOL_SCHEMAS_SHA256
        ):
            raise IdentityDrift("live ce-v1 prompt or tool surface drifted")
        if re.fullmatch(r"sha256:[0-9a-f]{64}", self.image_digest) is None:
            raise IdentityDrift("image digest must be an exact sha256 digest")
        if (
            not self.per_attempt_cap_usd.is_finite()
            or self.per_attempt_cap_usd <= 0
            or not self.total_cap_usd.is_finite()
            or self.total_cap_usd <= 0
        ):
            raise MissingSpendCap(
                "MissingSpendCap: positive per-attempt and total spend caps are required"
            )
        bound = self.pricing.conservative_request_bound_usd
        if bound is None and not self.pricing.basis:
            raise UnknownPricing(
                "UnknownPricing: pricing basis or conservative per-request bound required"
            )
        if bound is not None and (not bound.is_finite() or bound <= 0):
            raise UnknownPricing("UnknownPricing: conservative per-request bound must be positive")
        if bound is not None and bound > self.per_attempt_cap_usd:
            raise MissingSpendCap(
                "MissingSpendCap: per-request reservation exceeds per-attempt cap"
            )
        return self

    @classmethod
    def load(cls, path: Path) -> Self:
        return cls.model_validate_json(path.read_bytes())

    def canonical_bytes(self) -> bytes:
        return canonical_json(self.model_dump(mode="json"))

    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes())
