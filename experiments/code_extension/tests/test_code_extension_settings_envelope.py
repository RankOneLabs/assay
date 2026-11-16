"""Named bounds preserve qualified library identities."""

import json
from pathlib import Path

import pytest
from assay_pier_bridge.agent_loop import PAID_TURN_ROUTES
from assay_pier_bridge.protocol import ModelRoute
from code_extension.bridge import ExtensionBridgeClient
from code_extension.config import RunConfiguration
from code_extension.settings import ExtensionAgentSettings, UnauthorizedExtensionRoute

BASELINE_DIGESTS = {
    (
        'experiments/code_extension/studies/matched-tasks-2026-11/study-ministral.json'
    ): 'sha256:96368c4c3e2dde26f357e935fb066b7d76d5bc62695b5389185f98f1af4d123b',
    (
        'experiments/code_extension/studies/matched-tasks-2026-11/calibration-ministral.json'
    ): 'sha256:3ede244b00029da0a4ee26b06fbcba3a7162956ac36e64681d558740c24dd9dc',
    (
        'experiments/code_extension/studies/matched-tasks-2026-11/calibration-qwen.json'
    ): 'sha256:52b56be58638aa88aeec61c902fcc9ecf2be8f6e17023407525453326d966067',
    (
        'experiments/code_extension/studies/matched-tasks-2026-11/third-model-sol.json'
    ): 'sha256:284b0ba924816056ed6b2d7643f4dffe25adfdd320a7c4c6494e595a6c4a342f',
    (
        'experiments/code_extension/studies/matched-tasks-2026-11/control-ministral.json'
    ): 'sha256:1c03de98dfe207cf43a8f9ce43bcec50334ed407a17fdea3c5f92d20a8ce75e1',
    (
        'experiments/code_extension/studies/matched-tasks-2026-11/study-qwen.json'
    ): 'sha256:5a11dc013e40b8b81fe2994179b03ea9809077cfbfbee5866de0c7d88dbb5107',
    (
        'experiments/code_extension/studies/matched-tasks-2026-11/control-qwen.json'
    ): 'sha256:9a140441e6f6d20e1264de40f612d22b4c9c4d60a97eef0fdb04b192c0412d65',
    (
        'experiments/code_extension/studies/scenario-library/study-ministral.json'
    ): 'sha256:b8b2b9a6f29885dece1591de05d99cbe787eae85cd87581707c636630ad0199e',
    (
        'experiments/code_extension/studies/scenario-library/calibration-ministral.json'
    ): 'sha256:80e6a1befc576be0a964c92b634d4cc3c402930f4643bad2c86bebb0e87019f3',
    (
        'experiments/code_extension/studies/scenario-library/calibration-qwen.json'
    ): 'sha256:db2396b243153ada407b23f0f6aa59fb5992877b4a11d189dbfc389e06ef37ba',
    (
        'experiments/code_extension/studies/scenario-library/calibration-sol.json'
    ): 'sha256:2cd881ae155bf9f54aad760e3354698a91c38adb52f4c30cf6aaca671b05d4a3',
    (
        'experiments/code_extension/studies/scenario-library/study-sol.json'
    ): 'sha256:840b30844eb4d35507cb213db20b2e2ead995da14425472e9d86512cd7dd9bc2',
    (
        'experiments/code_extension/studies/scenario-library/study-qwen.json'
    ): 'sha256:7bd0eabdd13728d9796046bebf6b50a24f66feed7dac5a444c9207f5e5f8d149',
    (
        'experiments/code_extension/studies/scenario-library/calibration-sol-recheck.json'
    ): 'sha256:c412c2b340d9750fe94395b370b9e041fc8139b0b330f765ea90f04e687babf8',
}


@pytest.mark.parametrize("model", ["qwen-coder-32b", "qwen3.6-27b",
                                   *sorted({key[0] for key in PAID_TURN_ROUTES})])
def test_library_envelope_is_unchanged(model: str) -> None:
    assert ExtensionAgentSettings.for_model(model, envelope="library-v1") == (
        ExtensionAgentSettings.for_model(model)
    )


def test_committed_configuration_digests() -> None:
    root = Path(__file__).resolve().parents[3]
    for path, digest in BASELINE_DIGESTS.items():
        config = RunConfiguration.load(root / path)
        assert config.digest() == digest
        assert "envelope" not in json.loads(config.canonical_bytes())


def test_study_bounds_and_configuration() -> None:
    root = Path(__file__).resolve().parents[3]
    original = RunConfiguration.load(root / next(iter(BASELINE_DIGESTS)))
    bounds = ExtensionAgentSettings.for_model("openai/gpt-6.1-sol", envelope="fact-shapes-v1")
    assert bounds.max_turns == 80
    assert bounds.timeout_s == 1800.0
    assert bounds.request_timeout_s == 120.0
    assert bounds.max_output_tokens == 8192
    assert bounds.max_tool_output_bytes == 32768
    assert bounds.concurrency == bounds.attempts == 1
    assert bounds.provider_retries == bounds.sdk_retries == 0
    assert bounds.served_context_tokens is bounds.model_context_limit_tokens is None
    assert bounds.max_conversation_bytes == 3_670_016
    assert bounds.max_request_bytes == 3_932_160
    data = original.model_dump(mode="json")
    data.update(route={"endpoint": "https://openrouter.ai/api/v1",
                       "model": "openai/gpt-6.1-sol", "provider": "azure/us"},
                bounds=bounds.model_dump(mode="json"), envelope="fact-shapes-v1")
    config = RunConfiguration.model_validate(data)
    assert json.loads(config.canonical_bytes())["envelope"] == "fact-shapes-v1"
    del data["envelope"]
    with pytest.raises(ValueError, match="bounds differ from qualified model envelope"):
        RunConfiguration.model_validate(data)


def test_refuse_local_and_unknown_envelopes() -> None:
    with pytest.raises(UnauthorizedExtensionRoute):
        ExtensionAgentSettings.for_model("qwen-coder-32b", envelope="fact-shapes-v1")
    with pytest.raises(ValueError, match="unknown extension bound envelope"):
        ExtensionAgentSettings.for_model("qwen-coder-32b", envelope="unknown")  # type: ignore[arg-type]


def test_bridge_selects_study_envelope(tmp_path: Path) -> None:
    route = ModelRoute(endpoint="https://openrouter.ai/api/v1",
                       model="openai/gpt-6.1-sol", provider="azure/us")
    bounds = ExtensionAgentSettings.for_model(route.model, envelope="fact-shapes-v1")
    bridge = ExtensionBridgeClient(image="test", runs_root=tmp_path, factory=None,
                                   run_label="study", route=route, settings=bounds,
                                   envelope="fact-shapes-v1")
    assert bridge._settings() == bounds
    assert bridge._bounds().max_turns == 80
    assert bridge._bounds().max_output_tokens == 8192
    bridge.envelope = "library-v1"
    with pytest.raises(ValueError, match="extension ceilings differ"):
        bridge._settings()


@pytest.mark.usefixtures("qualified_runner")
def test_run_forwards_envelope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from code_extension.run import _build

    from assay.store import ObjectStore

    root = Path(__file__).resolve().parents[3]
    config = RunConfiguration.load(
        root / 'experiments/code_extension/studies/scenario-library/study-sol.json'
    )
    data = config.model_dump(mode="json")
    data.update(envelope="fact-shapes-v1", bounds=ExtensionAgentSettings.for_model(
        config.route.model, envelope="fact-shapes-v1",
    ).model_dump(mode="json"))
    config = RunConfiguration.model_validate(data)
    monkeypatch.setattr(
        "code_extension.bridge.observed_image_digest", lambda _: config.image_digest,
    )
    prepared = _build(config, ObjectStore(tmp_path), live=False)
    for worker in prepared.workers.values():
        for bridge in worker.bridges.values():
            assert bridge.envelope == "fact-shapes-v1"
            assert bridge._settings() == config.bounds
