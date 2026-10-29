"""Settled factor tags, baseline arm, and declared code-intelligence deliveries."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from pydantic import TypeAdapter

from assay.code_intel.delivery import CodeIntelDeliveryConfig
from assay.code_intel.models import (
    BaselineMode,
    PreloadedDelivery,
    RelationshipsMode,
    SymbolsMode,
    ToolDelivery,
)
from assay.fixture_manifest import CodeIntelligenceModeArmSet
from assay.models import Identifier

ArmSetFactor = Literal[
    "code_shape", "handoff_detail", "model_profile", "code_intelligence_mode", "baseline"
]
ARM_SET_FACTORS: tuple[ArmSetFactor, ...] = (
    "code_shape",
    "handoff_detail",
    "model_profile",
    "code_intelligence_mode",
    "baseline",
)

BASELINE_ARM_ID: str = TypeAdapter(Identifier).validate_python("baseline")
BASELINE_ARM_IDS: tuple[str, ...] = (BASELINE_ARM_ID,)

# The mount is an image-side index location, outside the submitted /workspace.
# Readability is recorded operator policy; it is not an enforced access boundary.
INDEX_MOUNT = "/cache/codeintel"


@dataclass(frozen=True)
class CodeIntelArmPolicy:
    mode: BaselineMode | SymbolsMode | RelationshipsMode
    delivery: ToolDelivery | PreloadedDelivery
    index_agent_readable: bool


CODE_INTEL_ARM_POLICIES: Mapping[str, CodeIntelArmPolicy] = MappingProxyType({
    "baseline": CodeIntelArmPolicy(BaselineMode(), ToolDelivery(), False),
    "symbols": CodeIntelArmPolicy(SymbolsMode(), ToolDelivery(), True),
    "relationships": CodeIntelArmPolicy(RelationshipsMode(), PreloadedDelivery(), False),
})


def codeintel_arm_configs(
    arm_set: CodeIntelligenceModeArmSet,
    *,
    repository_revision: str,
    max_context_tokens: int,
    query_limit: int,
) -> dict[str, CodeIntelDeliveryConfig]:
    """Bind each declared mode and delivery to the fixture's repository revision."""
    unknown = set(arm_set.arm_ids) - CODE_INTEL_ARM_POLICIES.keys()
    if unknown:
        raise ValueError(f"undeclared code-intelligence arm: {sorted(unknown)[0]}")
    return {
        arm_id: CodeIntelDeliveryConfig(
            mode=CODE_INTEL_ARM_POLICIES[arm_id].mode,
            delivery=CODE_INTEL_ARM_POLICIES[arm_id].delivery,
            repository_revision=repository_revision,
            max_context_tokens=max_context_tokens,
            query_limit=query_limit,
            index_mount=INDEX_MOUNT,
            index_agent_readable=CODE_INTEL_ARM_POLICIES[arm_id].index_agent_readable,
        )
        for arm_id in arm_set.arm_ids
    }


def require_declared_codeintel_arm(
    arm_set: CodeIntelligenceModeArmSet | None,
    arm_id: str,
    config: CodeIntelDeliveryConfig | None,
) -> None:
    """Refuse an undeclared mode, delivery, or mount before any cell dispatch."""
    if arm_set is None:
        return
    policy = CODE_INTEL_ARM_POLICIES.get(arm_id)
    if arm_id not in arm_set.arm_ids or policy is None:
        raise ValueError(f"undeclared code-intelligence arm: {arm_id}")
    if config is None:
        if isinstance(policy.mode, BaselineMode):
            return
        raise ValueError(f"missing code-intelligence delivery: {arm_id}")
    if (
        config.mode != policy.mode
        or config.delivery != policy.delivery
        or config.index_mount != INDEX_MOUNT
        or config.index_agent_readable != policy.index_agent_readable
    ):
        raise ValueError(f"code-intelligence delivery differs from declared arm: {arm_id}")
