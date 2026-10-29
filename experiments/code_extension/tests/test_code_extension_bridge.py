"""Extension prompt, route and provider gates before a model call."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from code_extension.arms import (
    CODE_INTEL_ARM_POLICIES,
    INDEX_MOUNT,
    codeintel_arm_configs,
    require_declared_codeintel_arm,
)
from code_extension.bridge import (
    EXTENSION_TOOLS,
    ExtensionBridgeClient,
    SandboxLimits,
    UnauthorizedModelRoute,
    index_sandbox_options,
    require_authorized_route,
)
from code_extension.codeintel import prepare_extension_codeintel
from code_extension.prompts import render_arm_prompts
from code_extension.settings import DERIVATION_SOURCE, ExtensionAgentSettings
from workflow_edit.arms import MESS_00
from workflow_edit.evaluation import CellEvaluator, envelope_bytes, worker_candidate
from workflow_edit.tests.test_workflow_edit_study import (
    SUBJECT,
    RecordingRunner,
    _envelope,
    _output,
    _study,
    _tree,
)

from assay.adapters.pier import PierAdapter
from assay.canonical import canonical_json
from assay.code_intel.delivery import CodeIntelDeliveryConfig
from assay.code_intel.errors import Ok
from assay.code_intel.models import (
    IndexManifest,
    PreloadedDelivery,
    PreloadedSummary,
    QueryResult,
    RelationshipsMode,
    SymbolsMode,
    ToolDelivery,
)
from assay.code_intel.snapshot import make_index_manifest, repo_revision
from assay.execution import WorkerFailure
from assay.fixture_manifest import (
    CodeIntelligenceModeArmSet,
    ExtensionArmRealization,
    ExtensionScenario,
    HandoffDetailArmSet,
    NamedTestGroup,
)
from assay.investigations.workflow_correctness import workflow_tree_digest
from assay.models import CellCoordinate, EvaluationCoordinate
from assay.pier_protocol import ModelRoute, RuntimeBinding
from assay.store import ObjectStore

SHA = "sha256:" + "a" * 64
TREE = "sha256:" + "b" * 64


def test_extension_settings_match_image_copy_and_scale_with_served_context() -> None:
    root = Path(__file__).resolve().parents[3]
    image_settings = yaml.safe_load(
        (root / "integrations/pier/config/code_extension.yaml").read_text()
    )
    assert image_settings == {"routes": {
        model: ExtensionAgentSettings.for_model(model).model_dump()
        for model in ("qwen-coder-32b", "qwen3.6-27b")
    }}
    assert ExtensionAgentSettings.for_model("qwen-coder-32b") != (
        ExtensionAgentSettings.for_model("qwen3.6-27b")
    )
    assert all(
        DERIVATION_SOURCE in (field.description or "")
        for field in ExtensionAgentSettings.model_fields.values()
    )


def _scenario(prompts: tuple[str, str]) -> ExtensionScenario:
    arms = tuple(
        ExtensionArmRealization.model_construct(
            arm_id=arm_id, tree_digest=TREE, task_prompt=prompt,
            reference_patch=SHA, negative_patches=(SHA,), qualification=None,
        )
        for arm_id, prompt in zip(("a", "b"), prompts, strict=True)
    )
    return ExtensionScenario.model_construct(
        subject_id="subject", checkpoint_sha="a" * 40,
        included_paths=("src/",), excluded_paths=(), dependency_lock_digests={},
        feature_request="Add a feature", visible_requirements=("works",),
        visible_tests=(NamedTestGroup(name="visible", digest=SHA),),
        hidden_tests=(NamedTestGroup(name="hidden", digest=TREE),), arms=arms,
    )


def test_handoff_prompts_are_distinct_and_other_factors_share_one_prompt() -> None:
    handoff = HandoffDetailArmSet(factor="handoff_detail", arm_ids=("a", "b"))
    scenario = _scenario(("High-level feature request", "Edit src/feature.ts"))
    assert len(set(render_arm_prompts(handoff, scenario).values())) == 2
    assert len({arm.tree_digest for arm in scenario.arms}) == 1
    assert tuple(group.digest for group in scenario.hidden_tests) == (TREE,)
    with pytest.raises(ValueError, match="distinct"):
        render_arm_prompts(handoff, _scenario(("same", "same")))
    intel = CodeIntelligenceModeArmSet(factor="code_intelligence_mode", arm_ids=("a", "b"))
    assert render_arm_prompts(intel, _scenario(("same", "same"))) == {
        "a": "same", "b": "same",
    }
    with pytest.raises(ValueError, match="byte-identical"):
        render_arm_prompts(intel, scenario)


def test_codeintel_arm_set_declares_mount_mode_and_delivery_together() -> None:
    arm_set = CodeIntelligenceModeArmSet(
        factor="code_intelligence_mode", arm_ids=("symbols", "relationships")
    )
    configs = codeintel_arm_configs(
        arm_set, repository_revision=SHA, max_context_tokens=512, query_limit=10,
    )
    assert set(configs) == set(arm_set.arm_ids)
    assert {config.index_mount for config in configs.values()} == {INDEX_MOUNT}
    assert isinstance(configs["symbols"].mode, SymbolsMode)
    assert isinstance(configs["symbols"].delivery, ToolDelivery)
    assert isinstance(configs["relationships"].mode, RelationshipsMode)
    assert isinstance(configs["relationships"].delivery, PreloadedDelivery)
    assert CODE_INTEL_ARM_POLICIES["relationships"].index_agent_readable is False
    for arm_id, config in configs.items():
        require_declared_codeintel_arm(arm_set, arm_id, config)
    with pytest.raises(ValueError, match="differs from declared arm"):
        require_declared_codeintel_arm(
            arm_set, "relationships", configs["relationships"].model_copy(update={
                "delivery": ToolDelivery(),
            }),
        )
    with pytest.raises(ValueError, match="missing code-intelligence delivery"):
        require_declared_codeintel_arm(arm_set, "symbols", None)
    with pytest.raises(ValueError, match="undeclared code-intelligence arm"):
        codeintel_arm_configs(
            CodeIntelligenceModeArmSet(factor="code_intelligence_mode", arm_ids=("a", "b")),
            repository_revision=SHA, max_context_tokens=512, query_limit=10,
        )


def test_unauthorized_route_is_typed_and_never_dispatches() -> None:
    model_calls = 0

    def dispatch() -> None:
        nonlocal model_calls
        model_calls += 1

    route = ModelRoute(
        endpoint="https://openrouter.ai/api/v1", model="openai/gpt-6.1-sol",
        provider="azure/us",
    )
    with pytest.raises(UnauthorizedModelRoute, match="unauthorized"):
        require_authorized_route(route)
        dispatch()
    assert model_calls == 0


@pytest.mark.asyncio
async def test_unauthorized_route_settles_at_cell_boundary(tmp_path: Path) -> None:
    class FakeFactory:
        model_calls = 0

        def configuration(self) -> dict[str, str]:
            return {"model": "openai/gpt-6.1-sol"}

        def create(self, **_kwargs: Any) -> Any:
            self.model_calls += 1
            raise AssertionError("unauthorized route reached provider")

    factory = FakeFactory()
    route = ModelRoute(
        endpoint="https://openrouter.ai/api/v1", model="openai/gpt-6.1-sol",
        provider="azure/us",
    )
    arm_set = CodeIntelligenceModeArmSet(factor="code_intelligence_mode", arm_ids=("a", "b"))
    bridge = ExtensionBridgeClient(
        image="unbuilt", runs_root=tmp_path, factory=factory, run_label="run",
        scenario=_scenario(("Implement feature", "Implement feature")), arm_set=arm_set,
        arm_id="a", route=route,
    )
    adapter = PierAdapter(
        store=ObjectStore(tmp_path / "store"), bridge=bridge,
        binding=RuntimeBinding(
            runtime_version="extension-test", image_digest=SHA,
            configuration_ref=SHA, package_digest=SHA,
        ),
        model_route=route.model_dump(),
        trial_limits={"cpu": 1.0, "memory_mb": 1536, "pids": 128,
                      "timeout_s": 900.0, "storage_mb": 512},
        package_layout="submission-worktree",
    )
    result = await adapter.run_cell(
        input_value={"task": "Implement feature", "repository": {"src/a.ts": "export {};\n"}},
        coordinate=CellCoordinate(
            subject_id="subject", arm_id="a", worker_repeat=0, realization_ref=SHA,
        ),
    )
    assert isinstance(result, WorkerFailure)
    assert result.error_type == "UnauthorizedModelRoute"
    assert factory.model_calls == 0


class InjectedProvider:
    def __init__(self, snapshot: dict[str, str], source: str) -> None:
        self.snapshot = snapshot
        self.source = source
        self.excluded_paths: frozenset[str] | None = None

    def prepare(self, *_args: Any, **_kwargs: Any) -> Any:
        self.excluded_paths = _kwargs["excluded_paths"]
        manifest = make_index_manifest(
            self.snapshot, image_digest=SHA, indexer_version="test/1",
            excluded_paths=self.excluded_paths, indexed_paths=self.snapshot,
        )
        if self.source == "index_manifest":
            manifest = manifest.model_copy(update={"tool_versions": {"planted": "HIDDEN_SOURCE"}})
        return Ok(manifest)

    def summarize(self, manifest: IndexManifest, **_kwargs: Any) -> Any:
        text = "HIDDEN_SOURCE" if self.source == "summary" else "public"
        return Ok(PreloadedSummary(repo_revision=manifest.repo_revision, text=text))

    def query(self, manifest: IndexManifest, kind: str, text: str) -> Any:
        snippet = "HIDDEN_SOURCE" if self.source == "query" else "public"
        return Ok(QueryResult(query_kind=kind, items=(), snippets=(snippet,)))

    def capabilities(self) -> Any:
        raise AssertionError("unused")

    def tools(self) -> tuple[dict[str, object], ...]:
        return ()

    def prompt_block(self) -> None:
        return None

    def prefix_block(self) -> tuple[dict[str, object], ...]:
        return ()

    def close(self) -> None:
        return None


@pytest.mark.parametrize("source", ["index_manifest", "summary", "query"])
def test_pre_run_leak_scan_refuses_each_delivery_source(tmp_path: Path, source: str) -> None:
    snapshot = {"src/visible.ts": "export const visible = true;", "src/hidden.ts": "secret"}
    config = CodeIntelDeliveryConfig(
        mode=SymbolsMode(), delivery=PreloadedDelivery(),
        repository_revision=repo_revision(snapshot), max_context_tokens=512,
        query_limit=10, index_mount="/cache/codeintel", index_agent_readable=False,
    )
    with pytest.raises(ValueError, match=f"codeintel_leak: {source}"):
        prepare_extension_codeintel(
            snapshot=snapshot, hidden_paths=frozenset({"src/hidden.ts"}),
            hidden_source_texts=(), term_patterns=("HIDDEN_SOURCE",),
            preflight_queries=(("symbol", "visible"),), image_digest=SHA,
            index_root=tmp_path, config=config, baseline_tools=[],
            provider=InjectedProvider(snapshot, source),
        )


def test_hidden_check_path_is_passed_to_index_preparation(tmp_path: Path) -> None:
    snapshot = {
        "src/visible.ts": "export function visible() { return true; }",
        "src/hidden.ts": "export const HIDDEN_SOURCE = true;",
    }
    config = CodeIntelDeliveryConfig(
        mode=SymbolsMode(), delivery=PreloadedDelivery(),
        repository_revision=repo_revision(snapshot), max_context_tokens=512,
        query_limit=10, index_mount="/cache/codeintel", index_agent_readable=False,
    )
    provider = InjectedProvider(snapshot, "")
    prepared = prepare_extension_codeintel(
        snapshot=snapshot, hidden_paths=frozenset({"src/hidden.ts"}),
        hidden_source_texts=(snapshot["src/hidden.ts"],), term_patterns=("HIDDEN_SOURCE",),
        preflight_queries=(), image_digest=SHA, index_root=tmp_path,
        config=config, baseline_tools=[], provider=provider,
    )
    assert provider.excluded_paths == frozenset({"src/hidden.ts"})
    assert "src/hidden.ts" not in prepared.manifest.indexed_paths
    assert prepared.delivery.index_mount == "/cache/codeintel"
    assert prepared.delivery.index_agent_readable is False
    assert index_sandbox_options(prepared, config, SandboxLimits())[
        "index_agent_readable"
    ] is True


def test_tool_delivery_appends_to_extension_surface_and_records_policy(tmp_path: Path) -> None:
    snapshot = {"src/visible.ts": "export const visible = true;"}
    config = CodeIntelDeliveryConfig(
        mode=SymbolsMode(), delivery={"kind": "tool"},
        repository_revision=repo_revision(snapshot), max_context_tokens=512,
        query_limit=10, index_mount="/cache/codeintel", index_agent_readable=True,
    )
    prepared = prepare_extension_codeintel(
        snapshot=snapshot, hidden_paths=frozenset(), hidden_source_texts=(),
        term_patterns=(), preflight_queries=(), image_digest=SHA,
        index_root=tmp_path, config=config, baseline_tools=EXTENSION_TOOLS,
        provider=InjectedProvider(snapshot, ""),
    )
    assert prepared.tools[:len(EXTENSION_TOOLS)] == EXTENSION_TOOLS
    assert prepared.tools[-1]["function"]["name"] == "codeintel_query"
    assert prepared.delivery.index_agent_readable is True


@pytest.mark.asyncio
async def test_self_assessment_does_not_change_evaluator_inputs_or_verdict(tmp_path: Path) -> None:
    store, fixture = _study(tmp_path)
    runner = RecordingRunner()
    evaluator = CellEvaluator(store, fixture.manifest, runner)  # type: ignore[arg-type]
    coordinate = EvaluationCoordinate(
        cell_id=f"{SUBJECT}:{MESS_00}:w0", evaluator_id="correctness", evaluator_repeat=0,
    )
    repository = _tree(MESS_00)
    output = _output(
        store, coordinate.cell_id, repository,
        baseline_digest=workflow_tree_digest(repository),
    )
    original = json.loads(envelope_bytes(store, output["result_ref"]))
    assessed = {**output, "result_ref": _envelope(
        store, "result.json", canonical_json({
            **original,
            "submissions": [{
                "summary": "done", "self_assessed_verdict": "unsure",
                "checks_performed": "typecheck", "remaining_work": "none",
            }],
        }),
    )}
    assert worker_candidate(store, output) == worker_candidate(store, assessed)
    first = await evaluator.evaluate(
        input_value={"repository": repository}, output=output, coordinate=coordinate,
    )
    second = await evaluator.evaluate(
        input_value={"repository": repository}, output=assessed, coordinate=coordinate,
    )
    assert first == second
    assert runner.calls[0] == runner.calls[1]
