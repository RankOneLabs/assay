"""Versioned identity of a workflow fixture and its operator-held assets."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from assay.canonical import canonical_json, digest_bytes
from assay.models import Identifier, NonEmpty, Sha256Ref, WireModel

CheckpointSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]


class TreatmentSite(WireModel):
    """A path and description of one intentional treatment location."""

    path: NonEmpty
    description: NonEmpty


class FixtureManifest(WireModel):
    """All identity-bearing inputs of a fixture, with hidden assets by digest only.

    ``observed_runtime_image_digest`` is the digest inspected from the built
    image, not a value declared before the build. Hidden tests, patches, and
    rubric cannot be inlined in this closed wire shape.
    """

    schema_version: Literal["assay-fixture-manifest/0.1.0"]
    checkpoint_sha: CheckpointSha
    included_paths: tuple[str, ...]
    excluded_paths: tuple[str, ...]
    dependency_lock_digests: dict[str, Sha256Ref]
    observed_runtime_image_digest: Sha256Ref
    normalization_diff: str
    treatment_site_inventory: tuple[TreatmentSite, ...]
    per_arm_tree_digests: dict[Identifier, Sha256Ref] = Field(
        json_schema_extra={"additionalProperties": False}
    )
    transformation_version: NonEmpty
    equivalence_test_version: NonEmpty
    task_prompt: NonEmpty
    hidden_tests: tuple[Sha256Ref, ...] = Field(min_length=1)
    reference_patch: Sha256Ref
    negative_patches: tuple[Sha256Ref, ...] = Field(min_length=1)
    rubric: Sha256Ref
    routing_config_digest: Sha256Ref


def fixture_identity(manifest: FixtureManifest) -> str:
    """Digest the complete canonical manifest, including image and routing."""
    return digest_bytes(canonical_json(manifest.model_dump(mode="json")))
