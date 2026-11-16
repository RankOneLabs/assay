"""Frozen plan identity, allocation and reservation checks; never dispatch models."""

import json
from decimal import Decimal
from pathlib import Path

from code_extension.config import RunConfiguration
from code_extension.fact_shapes.settings import STUDY_MODELS
from code_extension.settings import ExtensionAgentSettings

from assay.canonical import digest_bytes

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "studies/fact-shapes-2026-11"


def test_frozen_cohorts() -> None:
    expected_attempts = {
        "pilot": {"sol": 12, "argon": 6, "midtier": 6},
        "study": {"sol": 180, "argon": 180, "midtier": 180},
    }
    for cohort, expected in expected_attempts.items():
        request = json.loads((STUDY / f"{cohort}.json").read_bytes())
        assert {plan["name"] for plan in request["plans"]} == set(expected)
        total = Decimal(0)
        attempts = 0
        for plan in request["plans"]:
            model = next(model for model in STUDY_MODELS if model.name == plan["name"])
            config = RunConfiguration.model_validate_json((STUDY / plan["config"]).read_bytes())
            assert config.envelope == "fact-shapes-v1"
            assert config.route == model.route
            assert config.concurrency == 1
            assert config.bounds == ExtensionAgentSettings.for_model(
                model.route.model, envelope="fact-shapes-v1"
            )
            count = 0
            for ref in config.scenario_qualifications:
                path = ROOT / "fixtures" / ref.scenario / "qualification/manifest.json"
                assert digest_bytes(path.read_bytes()) == ref.manifest_digest
                manifest = json.loads(path.read_bytes())
                assert manifest["observed_runtime_image_digest"] == config.image_digest
                assert manifest["arm_set"]["factor"] == "code_shape"
                assert len(manifest["arm_set"]["arm_ids"]) == 6
                count += 6 * config.repeats
            assert count == expected[model.name]
            assert len(config.scenario_qualifications) == (1 if cohort == "pilot" else 6)
            assert config.total_cap_usd >= (count + 1) * config.per_attempt_cap_usd
            total += config.total_cap_usd
            attempts += count
        assert attempts == (24 if cohort == "pilot" else 540)
        assert total <= Decimal(request["combined_cap_usd"])
