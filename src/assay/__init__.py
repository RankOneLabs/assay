"""Content-addressed, paired agent experiments."""

from assay._version import __version__
from assay.canonical import CanonicalizationError, canonical_json, digest_bytes
from assay.execution import RunFailed, RunSucceeded, execute_plan
from assay.models import (
    Arm,
    EvaluatorDeclaration,
    ExecutionPlan,
    Realization,
    StudySnapshot,
    Subject,
)
from assay.planning import AuthorizationError, compile_plan
from assay.store import ObjectRef, ObjectStore

__all__ = [
    "Arm",
    "AuthorizationError",
    "CanonicalizationError",
    "EvaluatorDeclaration",
    "ExecutionPlan",
    "ObjectRef",
    "ObjectStore",
    "Realization",
    "RunFailed",
    "RunSucceeded",
    "StudySnapshot",
    "Subject",
    "canonical_json",
    "compile_plan",
    "digest_bytes",
    "execute_plan",
    "__version__",
]
