"""A trial's evidence bytes must survive the handle that produced them.

``teardown`` destroys the submission mount, so bytes not carried out on the
``TrialResult`` are gone -- and the trial's own output directory is the
least trustworthy thing this project reads, so carrying them out is bounded
and refuses to follow what a model may have planted there.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import get_args

import pytest
from assay_pier_bridge.container import DockerTrialClient
from assay_pier_bridge.evidence import worker_usage_from_result_bytes
from assay_pier_bridge.identity import canonical_json, digest_bytes
from assay_pier_bridge.paths import (
    ArtifactCollectionRejected,
    collect_artifacts,
    regular_tree,
    submission_patch,
    tree_digest,
)
from assay_pier_bridge.protocol import (
    MANIFEST_PATH,
    MAX_AGGREGATE_ARTIFACT_BYTES,
    MAX_ARTIFACT_BYTES,
    MAX_ARTIFACT_COUNT,
    MAX_SUBMISSION_ENTRIES,
    REQUIRED_SUCCESS_KINDS,
    ArtifactKind,
    ArtifactManifest,
    CandidateSubmission,
    EffectiveEnforcement,
    ModelRoute,
    TrialLimits,
    TrialRequest,
    TrialResult,
)
from assay_pier_bridge.runtime import BridgeRuntime, CandidateTrialError, seal_observed_artifacts
from pydantic import ValidationError
from test_container_lifecycle import PACKAGE, _request
from test_support import exchange_for

pytest_plugins = ["test_container_lifecycle"]


def test_revision_three_artifact_contract_matches_shared_fixture() -> None:
    fixture_path = Path(__file__).parents[3] / "tests/fixtures/pier_wire_contract.json"
    contract = json.loads(fixture_path.read_text(encoding="utf-8"))["artifact_manifest"]
    assert set(get_args(ArtifactKind)) == set(contract["kinds"])
    assert set(contract["required_success_kinds"]) == REQUIRED_SUCCESS_KINDS
    manifest = ArtifactManifest(
        exchange=exchange_for("s1:a1:w0", "sha256:" + "0" * 64),
        entries=(),
        aggregate_bytes=0,
    )
    assert manifest.schema_version == contract["schema_version"]


def test_observing_seal_binds_two_candidate_files() -> None:
    files = {"a.py": b"a = 1\n", "b.py": b"b = 2\n"}
    artifacts = seal_observed_artifacts(
        exchange_for("s1:a1:w0", "sha256:" + "0" * 64),
        {
            "trajectory.json": b"{}",
            "candidate.patch": b"patch",
            "result.json": b'{"exit_status":"Submitted"}',
            "configuration.json": b"{}",
        },
        files,
        tree_digest(files),
    )
    manifest = ArtifactManifest.model_validate_json(artifacts[MANIFEST_PATH])
    assert {entry.kind for entry in manifest.entries} >= REQUIRED_SUCCESS_KINDS
    assert {entry.path for entry in manifest.entries if entry.kind == "candidate"} == {
        "candidate-index.json",
        "candidate_files/a.py",
        "candidate_files/b.py",
    }
    assert all(
        digest_bytes(artifacts[entry.path]) == entry.checksum
        and len(artifacts[entry.path]) == entry.size_bytes
        for entry in manifest.entries
    )


def test_real_container_dispatch_seals_every_observed_artifact(image: str) -> None:
    client = DockerTrialClient(
        image=image,
        package=PACKAGE,
        command=[
            "/bin/sh",
            "-c",
            "printf 'a = 1\\n' > /submission/worktree/a.py; "
            "printf 'b = 2\\n' > /submission/worktree/b.py; "
            "printf 'submitted' > /submission/output",
        ],
        openrouter_api_key="",
    )
    result = BridgeRuntime(client).run_cell(_request(network_policy="toolchain-only"))
    assert result.outcome.kind == "candidate", result.outcome
    manifest = ArtifactManifest.model_validate_json(result.artifacts[MANIFEST_PATH])
    assert {entry.kind for entry in manifest.entries} >= REQUIRED_SUCCESS_KINDS
    assert manifest.exchange == _request(network_policy="toolchain-only").exchange
    for entry in manifest.entries:
        data = result.artifacts[entry.path]
        assert len(data) == entry.size_bytes
        assert entry.checksum == digest_bytes(data)
    files = {
        entry.path.removeprefix("candidate_files/"): result.artifacts[entry.path]
        for entry in manifest.entries
        if entry.path.startswith("candidate_files/")
    }
    assert set(files) == {"a.py", "b.py"}
    assert result.outcome.tree_digest == tree_digest(files)


def _effective() -> EffectiveEnforcement:
    return EffectiveEnforcement(
        uid=1000,
        gid=1000,
        workspace_read_only=True,
        submission_mount="/submission",
        scratch_mount="/scratch",
        network_policy="none",
        cpu_limit=1.0,
        memory_limit_mb=512,
        pids_limit=64,
        storage_limit_mb=64,
        containers_remaining=0,
        child_processes_remaining=0,
        teardown_completed=True,
    )


def _result(**overrides: object) -> TrialResult:
    fields: dict[str, object] = {
        "cell_id": "s1:a1:w0",
        "outcome": CandidateSubmission(
            patch_ref="sha256:" + "0" * 64,
            tree_digest="sha256:" + "1" * 64,
            baseline_tree_digest="sha256:" + "2" * 64,
        ),
        "effective": _effective(),
    }
    fields.update(overrides)
    return TrialResult(**fields)  # type: ignore[arg-type]


def _collect(
    root: Path,
    *,
    max_bytes: int = MAX_ARTIFACT_BYTES,
    max_aggregate_bytes: int = MAX_AGGREGATE_ARTIFACT_BYTES,
    max_entries: int = MAX_SUBMISSION_ENTRIES,
) -> dict[str, bytes]:
    return collect_artifacts(
        root,
        max_bytes=max_bytes,
        max_aggregate_bytes=max_aggregate_bytes,
        max_entries=max_entries,
        aggregate_exempt_path=MANIFEST_PATH,
    )


def _failure_result(error: Exception) -> TrialResult:
    class Handle:
        def run(self) -> TrialResult:
            raise error

        def teardown(self) -> EffectiveEnforcement:
            return _effective()

    class Client:
        def create(self, request: TrialRequest) -> Handle:
            return Handle()

    ref = "sha256:" + "0" * 64
    return BridgeRuntime(Client()).run_cell(
        TrialRequest(
            cell_id="s1:a1:w0",
            package_digest=ref,
            exchange=exchange_for("s1:a1:w0", ref),
            model_route=ModelRoute(),
            limits=TrialLimits(cpu=1, memory_mb=256, pids=32, timeout_s=20, storage_mb=64),
        )
    )


def test_a_result_carries_artifact_bytes() -> None:
    result = _result(artifacts={"output": b"answer = 42\n", "result.json": b"{}"})
    assert result.artifacts["output"] == b"answer = 42\n"


def test_a_result_defaults_to_no_artifacts() -> None:
    assert _result().artifacts == {}


def test_an_oversized_artifact_is_rejected_by_the_type() -> None:
    with pytest.raises(ValidationError, match="per-artifact byte limit"):
        _result(artifacts={"output": b"x" * (MAX_ARTIFACT_BYTES + 1)})


def test_an_unsafe_artifact_path_is_rejected_by_the_type() -> None:
    with pytest.raises(ValidationError, match="unsafe path"):
        _result(artifacts={"../escaped": b"x"})


def _blobs(count: int) -> dict[str, bytes]:
    return {f"declared-{index}.bin": b"\x00" * MAX_ARTIFACT_BYTES for index in range(count)}


def test_artifacts_past_the_aggregate_limit_are_rejected_by_the_type() -> None:
    artifacts = _blobs(MAX_AGGREGATE_ARTIFACT_BYTES // MAX_ARTIFACT_BYTES)
    artifacts["declared-over.bin"] = b"\x00"
    with pytest.raises(ValidationError, match="aggregate byte limit"):
        _result(artifacts=artifacts)


def test_too_many_empty_artifacts_are_rejected_by_the_type() -> None:
    artifacts = {f"empty-{index}": b"" for index in range(MAX_ARTIFACT_COUNT + 1)}
    with pytest.raises(ValidationError, match="artifact count limit"):
        _result(artifacts=artifacts)


def test_maximum_artifact_count_plus_manifest_is_accepted_by_the_type() -> None:
    artifacts = {f"empty-{index}": b"" for index in range(MAX_ARTIFACT_COUNT)}
    artifacts[MANIFEST_PATH] = b"{}"
    assert _result(artifacts=artifacts).artifacts.keys() == artifacts.keys()


def test_the_manifest_is_not_charged_to_the_aggregate_limit() -> None:
    """``MAX_AGGREGATE_ARTIFACT_BYTES`` bounds what a manifest may declare,
    and the manifest is never one of its own entries. Charging the binding
    document to the budget it bounds would fail an honest trial that filled
    the ceiling exactly, on the bytes that say what it produced."""
    artifacts = _blobs(MAX_AGGREGATE_ARTIFACT_BYTES // MAX_ARTIFACT_BYTES)
    artifacts[MANIFEST_PATH] = b'{"schema_version": "assay-pier-artifact-manifest/0.1.0"}'
    assert _result(artifacts=artifacts).artifacts[MANIFEST_PATH] == artifacts[MANIFEST_PATH]


def test_the_manifest_is_still_bounded_per_artifact() -> None:
    """Exempt from the aggregate ceiling is not exempt from every ceiling:
    what a trial can hand back stays bounded by the sum of the two."""
    with pytest.raises(ValidationError, match="per-artifact byte limit"):
        _result(artifacts={MANIFEST_PATH: b"\x00" * (MAX_ARTIFACT_BYTES + 1)})


def test_collect_artifacts_reads_regular_files_relative_to_the_root(tmp_path: Path) -> None:
    (tmp_path / "output").write_bytes(b"answer = 42\n")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "result.json").write_bytes(b'{"exit_status": "Submitted"}')
    artifacts = _collect(tmp_path)
    assert artifacts == {
        "output": b"answer = 42\n",
        "nested/result.json": b'{"exit_status": "Submitted"}',
    }


def test_collect_artifacts_never_follows_a_symlink_out_of_the_root(tmp_path: Path) -> None:
    """A model with write access to /submission can plant a symlink; reading
    through it would publish a host file as the trial's own evidence."""
    secret = tmp_path / "outside" / "secret"
    secret.parent.mkdir()
    secret.write_bytes(b"HOST SECRET")
    submission = tmp_path / "submission"
    submission.mkdir()
    (submission / "output").write_bytes(b"answer = 42\n")
    (submission / "stolen").symlink_to(secret)
    with pytest.raises(ArtifactCollectionRejected) as rejected:
        _collect(submission)
    assert rejected.value.cause == "escaping_symlink"
    assert rejected.value.artifacts == {"output": b"answer = 42\n"}
    assert b"HOST SECRET" not in b"".join(rejected.value.artifacts.values())


def test_collect_artifacts_rejects_an_oversized_file_without_reading_it(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"retained")
    oversized = tmp_path / "huge"
    oversized.write_bytes(b"x" * 64)
    with pytest.raises(ArtifactCollectionRejected) as rejected:
        _collect(tmp_path, max_bytes=32)
    assert rejected.value.cause == "oversized_artifact"
    assert rejected.value.artifacts == {"a": b"retained"}
    result = _failure_result(rejected.value)
    assert result.outcome.cause == "oversized_artifact"
    assert result.artifacts == {"a": b"retained"}


def test_collect_artifacts_bounds_a_file_that_grows_after_lstat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    growing = tmp_path / "growing"
    growing.write_bytes(b"x" * 64)
    original_lstat = Path.lstat

    def stale_lstat(path: Path, *args: object, **kwargs: object) -> os.stat_result:
        result = original_lstat(path, *args, **kwargs)
        if path == growing:
            values = list(result)
            values[6] = 1
            return os.stat_result(values)
        return result

    monkeypatch.setattr(Path, "lstat", stale_lstat)
    with pytest.raises(ArtifactCollectionRejected) as rejected:
        _collect(tmp_path, max_bytes=32)
    assert rejected.value.cause == "oversized_artifact"


def test_collect_artifacts_rejects_too_many_filesystem_entries(tmp_path: Path) -> None:
    for index in range(3):
        (tmp_path / f"empty-{index}").write_bytes(b"")
    with pytest.raises(ArtifactCollectionRejected) as rejected:
        _collect(tmp_path, max_entries=2)
    assert rejected.value.cause == "entry_limit"


def test_collect_artifacts_enforces_aggregate_bytes_while_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a").write_bytes(b"1234")
    (tmp_path / "b").write_bytes(b"5678")
    original_lstat = Path.lstat

    def stale_lstat(path: Path, *args: object, **kwargs: object) -> os.stat_result:
        result = original_lstat(path, *args, **kwargs)
        if path == tmp_path / "b":
            values = list(result)
            values[6] = 1
            return os.stat_result(values)
        return result

    monkeypatch.setattr(Path, "lstat", stale_lstat)
    with pytest.raises(ArtifactCollectionRejected) as rejected:
        _collect(tmp_path, max_bytes=8, max_aggregate_bytes=7)
    assert rejected.value.cause == "aggregate_artifact_limit"
    assert rejected.value.artifacts == {"a": b"1234", "b": b"567"}
    result = _failure_result(rejected.value)
    assert result.outcome.cause == "aggregate_artifact_limit"
    assert result.artifacts == rejected.value.artifacts


@pytest.mark.parametrize(
    ("filename", "payload", "cause"),
    [("z\\name", b"x", "traversal"), ("z.bin", b"\x00", "binary_payload")],
)
def test_regular_tree_rejects_typed_bad_paths_and_bytes(
    tmp_path: Path, filename: str, payload: bytes, cause: str
) -> None:
    (tmp_path / "output").write_bytes(b"working-copy output")
    (tmp_path / filename).write_bytes(payload)
    with pytest.raises(ArtifactCollectionRejected) as rejected:
        regular_tree(tmp_path)
    assert rejected.value.cause == cause
    assert rejected.value.origin == "working_copy"
    assert rejected.value.artifacts == {"output": b"working-copy output"}
    result = _failure_result(rejected.value)
    assert result.outcome.cause == cause
    assert result.artifacts == {"rejected_worktree/output": b"working-copy output"}


def test_regular_tree_rejects_a_symlinked_root_before_reading_host_files(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"host secret")
    worktree = tmp_path / "worktree"
    worktree.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ArtifactCollectionRejected) as rejected:
        regular_tree(worktree)
    assert rejected.value.cause == "escaping_symlink"
    assert rejected.value.artifacts == {}


@pytest.mark.parametrize("which", ["baseline", "final"])
def test_patch_rejects_the_reserved_git_namespace(tmp_path: Path, which: str) -> None:
    baseline = tmp_path / "baseline"
    final = tmp_path / "final"
    baseline.mkdir()
    final.mkdir()
    (tmp_path / which / ".git").mkdir()
    (tmp_path / which / ".git" / "config").write_bytes(b"[core]\n")
    with pytest.raises(ArtifactCollectionRejected) as rejected:
        submission_patch(baseline, final)
    assert rejected.value.cause == "out_of_scope_edit"
    assert rejected.value.rejected_path == ".git"


@pytest.mark.parametrize(
    ("file_limit", "total_limit", "payload", "cause", "retained"),
    [
        (4, 10, b"12345", "oversized_artifact", b"1234"),
        (10, 4, b"12345", "aggregate_artifact_limit", b"1234"),
    ],
)
def test_regular_tree_bounded_reads_retain_a_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    file_limit: int,
    total_limit: int,
    payload: bytes,
    cause: str,
    retained: bytes,
) -> None:
    monkeypatch.setattr("assay_pier_bridge.paths.MAX_ARTIFACT_BYTES", file_limit)
    monkeypatch.setattr("assay_pier_bridge.paths.MAX_AGGREGATE_ARTIFACT_BYTES", total_limit)
    (tmp_path / "large.txt").write_bytes(payload)
    with pytest.raises(ArtifactCollectionRejected) as rejected:
        regular_tree(tmp_path)
    assert rejected.value.cause == cause
    assert rejected.value.artifacts == {"large.txt": retained}


def test_regular_tree_bounds_entry_enumeration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("assay_pier_bridge.paths.MAX_SUBMISSION_ENTRIES", 2)
    for name in ("a", "b", "c"):
        (tmp_path / name).write_bytes(b"x")
    with pytest.raises(ArtifactCollectionRejected) as rejected:
        regular_tree(tmp_path)
    assert rejected.value.cause == "entry_limit"


@pytest.mark.parametrize("cause", ["out_of_scope_edit", "tampering"])
def test_candidate_rejection_carries_its_own_artifacts(cause: str) -> None:
    class Handle:
        def run(self) -> TrialResult:
            raise CandidateTrialError(cause, "rejected", artifacts={"output": b"evidence"})

        def teardown(self) -> EffectiveEnforcement:
            return _effective()

    class Client:
        def create(self, request: TrialRequest) -> Handle:
            return Handle()

    ref = "sha256:" + "0" * 64
    request = TrialRequest(
        cell_id="s1:a1:w0",
        package_digest=ref,
        exchange=exchange_for("s1:a1:w0", ref),
        model_route=ModelRoute(),
        limits=TrialLimits(cpu=1, memory_mb=256, pids=32, timeout_s=20, storage_mb=64),
    )
    result = BridgeRuntime(Client()).run_cell(request)
    assert result.outcome.kind == "candidate_failure"
    assert result.outcome.cause == cause
    assert result.artifacts == {"output": b"evidence"}


def test_rejected_worktree_paths_cannot_replace_submission_artifacts() -> None:
    class Handle:
        def run(self) -> TrialResult:
            raise ArtifactCollectionRejected(
                "binary_payload",
                "bad working copy",
                origin="working_copy",
                artifacts={"output": b"worktree", "manifest.json": b"worktree manifest"},
            )

        def partial_artifacts(self) -> dict[str, bytes]:
            return {
                "output": b"submission",
                "manifest.json": b"submission manifest",
                "rejected_worktree/output": b"candidate spoof",
            }

        def teardown(self) -> EffectiveEnforcement:
            return _effective()

    class Client:
        def create(self, request: TrialRequest) -> Handle:
            return Handle()

    ref = "sha256:" + "0" * 64
    result = BridgeRuntime(Client()).run_cell(
        TrialRequest(
            cell_id="s1:a1:w0",
            package_digest=ref,
            exchange=exchange_for("s1:a1:w0", ref),
            model_route=ModelRoute(),
            limits=TrialLimits(cpu=1, memory_mb=256, pids=32, timeout_s=20, storage_mb=64),
        )
    )
    assert result.outcome.cause == "binary_payload"
    assert result.artifacts == {
        "output": b"submission",
        "manifest.json": b"submission manifest",
        "rejected_worktree/output": b"worktree",
        "rejected_worktree/manifest.json": b"worktree manifest",
    }


def test_collect_artifacts_skips_a_non_regular_file(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / "fifo")
    (tmp_path / "output").write_bytes(b"answer = 42\n")
    assert _collect(tmp_path) == {"output": b"answer = 42\n"}


def test_observed_patch_is_repeatable_and_applies_to_baseline(tmp_path: Path) -> None:
    import subprocess

    baseline = tmp_path / "baseline"
    final = tmp_path / "final"
    replay = tmp_path / "replay"
    for root in (baseline, final, replay):
        root.mkdir()
    (baseline / "a.py").write_bytes(b"value = 1\n")
    (baseline / "gone.py").write_bytes(b"old = 1\n")
    (final / "a.py").write_bytes(b"value = 2\n")
    (final / "new.py").write_bytes(b"new = 1\n")
    (replay / "a.py").write_bytes(b"value = 1\n")
    (replay / "gone.py").write_bytes(b"old = 1\n")
    first = submission_patch(baseline, final)
    second = submission_patch(baseline, final)
    assert first == second
    assert first.patch.startswith(b"diff --git a/a.py b/a.py\n")
    subprocess.run(["git", "apply", "-"], input=first.patch, cwd=replay, check=True)
    assert tree_digest(regular_tree(replay)) == first.final_tree_digest
    assert tree_digest(regular_tree(baseline)) == first.baseline_tree_digest


def test_repository_attributes_cannot_rewrite_patch_bytes(tmp_path: Path) -> None:
    import subprocess

    baseline = tmp_path / "baseline"
    final = tmp_path / "final"
    replay = tmp_path / "replay"
    for root in (baseline, final, replay):
        root.mkdir()
        (root / ".gitattributes").write_bytes(b"*.txt text\n")
    (baseline / "x.txt").write_bytes(b"before\r\n")
    (final / "x.txt").write_bytes(b"after\r\n")
    (replay / "x.txt").write_bytes(b"before\r\n")
    captured = submission_patch(baseline, final)
    assert b"-before\r\n+after\r\n" in captured.patch
    subprocess.run(["git", "apply", "-"], input=captured.patch, cwd=replay, check=True)
    assert tree_digest(regular_tree(replay)) == captured.final_tree_digest


def test_unchanged_working_copy_is_zero_byte_patch(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    final = tmp_path / "final"
    baseline.mkdir()
    final.mkdir()
    (baseline / "a.py").write_bytes(b"answer = 1\n")
    (final / "a.py").write_bytes(b"answer = 1\n")
    candidate = submission_patch(baseline, final)
    assert candidate.patch == b""
    assert candidate.final_tree_digest == candidate.baseline_tree_digest


def test_patch_follows_the_filesystem_not_the_agents_declared_edits(tmp_path: Path) -> None:
    """The agent's claim about which files it edited is never a patch input.

    This candidate under-reports (it never mentions ``b.py``) and
    over-reports (it names a ``ghost.py`` it never wrote). The recorded
    patch must still be exactly the observed tree delta, and the immutable
    baseline must be byte-identical afterwards.
    """
    baseline = tmp_path / "baseline"
    worktree = tmp_path / "worktree"
    for root in (baseline, worktree):
        root.mkdir()
        (root / "a.py").write_bytes(b"value = 1\n")
        (root / "b.py").write_bytes(b"other = 1\n")
    (worktree / "a.py").write_bytes(b"value = 2\n")
    (worktree / "b.py").write_bytes(b"other = 2\n")
    baseline_before = tree_digest(regular_tree(baseline))

    captured = submission_patch(baseline, worktree)

    diffed = sorted(
        line.split(b" b/")[-1]
        for line in captured.patch.splitlines()
        if line.startswith(b"diff --git ")
    )
    assert diffed == [b"a.py", b"b.py"]
    assert b"ghost.py" not in captured.patch
    assert captured.baseline_tree_digest == baseline_before
    assert tree_digest(regular_tree(baseline)) == baseline_before


def test_worker_reported_counts_become_usage_without_a_cost() -> None:
    usage = worker_usage_from_result_bytes(
        canonical_json(
            {
                "exit_status": "Submitted",
                "usage": {"prompt_tokens": 12, "completion_tokens": 7, "requests": 2},
            }
        )
    )
    assert usage is not None
    assert (usage.prompt_tokens, usage.completion_tokens, usage.requests) == (12, 7, 2)
    assert usage.cost_usd is None


@pytest.mark.parametrize(
    "payload",
    [
        b'{"exit_status":"Submitted","usage":null}',
        b'{"exit_status":"Submitted"}',
        b'{"exit_status":"Submitted","usage":{"prompt_tokens":true,"completion_tokens":1}}',
        b'{"exit_status":"Submitted","usage":{"prompt_tokens":-1,"completion_tokens":1}}',
        b'{"exit_status":"Submitted","usage":{"prompt_tokens":1.5,"completion_tokens":1}}',
        b'{"exit_status":"Submitted","usage":{"completion_tokens":1}}',
        b"not json",
        b"[]",
        None,
    ],
)
def test_unusable_worker_counts_report_no_usage_at_all(payload: bytes | None) -> None:
    """``None`` here is what Assay turns into ``uncertain`` coverage; a
    fabricated zero would become a confident measured zero instead."""
    assert worker_usage_from_result_bytes(payload) is None
