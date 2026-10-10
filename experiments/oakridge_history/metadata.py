"""Capture inputs and environment facts omitted from Assay's metrics report."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

from assay.canonical import canonical_json
from assay.code_metrics.models import CodeMetricsReportV5
from assay.code_metrics.pins import DEPENDENCY_CRUISER

from .git_resolve import ResolvedCommit
from .model import ScopeSpec

NODE_VERSION = "v22.21.1"
NPX_VERSION = "10.9.4"


def _version(*command: str) -> str:
    return subprocess.check_output(command, text=True).strip()


def build_metadata(
    commit: ResolvedCommit,
    scope: ScopeSpec,
    resolved_exclusions: tuple[str, ...],
    report: CodeMetricsReportV5,
    *,
    strict_runtime_pins: bool = False,
) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    node_version = _version("node", "--version")
    npx_version = _version("npx", "--version")
    if strict_runtime_pins and (node_version != NODE_VERSION or npx_version != NPX_VERSION):
        raise RuntimeError(
            f"runtime pin mismatch: node {node_version} (expected {NODE_VERSION}), "
            f"npx {npx_version} (expected {NPX_VERSION})"
        )
    return {
        "snapshot_id": commit.snapshot.id,
        "commit_sha": commit.sha,
        "author_date": commit.author_date,
        "subject": commit.subject,
        "first_parent": commit.first_parent,
        "pr_number": commit.snapshot.pr_number,
        "requested_include_paths": list(commit.requested_include_paths),
        "archived_include_paths": list(commit.archived_include_paths),
        "resolved_away_include_paths": list(commit.resolved_away_include_paths),
        "exclude_globs": list(scope.exclude_globs),
        "resolved_exclusions": list(resolved_exclusions),
        "coverage": {
            language.language: {
                "files_seen": language.files_seen,
                "files_analyzed": language.files_analyzed,
                "modules_discovered": language.modules_discovered,
                "files_without_module": len(language.files_without_module),
            }
            for language in report.coverage.languages
        },
        "archive_file_list_digest": hashlib.sha256(
            canonical_json(list(commit.archive_files))
        ).hexdigest(),
        "assay_git_sha": _version("git", "-C", str(root), "rev-parse", "HEAD"),
        "uv_lock_digest": hashlib.sha256((root / "experiments/uv.lock").read_bytes()).hexdigest(),
        "node_version": node_version,
        "npx_version": npx_version,
        "node_pin": NODE_VERSION,
        "npx_pin": NPX_VERSION,
        "dependency_cruiser_version": DEPENDENCY_CRUISER.rsplit("@", 1)[1],
    }
