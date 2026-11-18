"""Write the fact-shapes cohort files from settings and the committed manifests.

Run from experiments/ with ``python -m code_extension.fact_shapes.cohorts`` after any
requalification. Each plan pins the current manifest digest of every scenario it runs,
so a stale pin can only come from a manifest that was not requalified. ``--check``
compares instead of writing.
"""

import argparse
import json
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from assay.canonical import digest_bytes
from code_extension.config import RunConfiguration
from code_extension.fact_shapes.cells import CELLS
from code_extension.fact_shapes.generate import scenario_name
from code_extension.fact_shapes.settings import (
    LIBRARY_RERUN_TOTAL_CAP_USD,
    PER_ATTEMPT_CAPS,
    PILOT_TOTAL_CAP_USD,
    STUDY_ENVELOPE,
    STUDY_MODELS,
    STUDY_TOTAL_CAP_USD,
    StudyModelName,
)
from code_extension.fixture import PILOT
from code_extension.protocol import ORDERED_TOOL_SCHEMAS_SHA256, SYSTEM_PROMPT_SHA256
from code_extension.settings import ExtensionAgentSettings

STUDY = PILOT.parent.parent / "studies" / "fact-shapes-2026-11"
SCENARIOS = tuple(dict.fromkeys(scenario_name(cell) for cell in CELLS))
PILOT_SCENARIOS = ("fact-shapes-stage-additive",)
SEED = 20261115
PRICING_BASIS = (
    "operator-set plan caps (2026-11-17) from measured means, including one probe per plan;"
    " per-attempt caps are request reservation headroom"
)

# Plan caps in USD. The study's split is provisional until the pilot measures Argon
# and the mid-tier route; the totals are fixed in settings.
PILOT_PLAN_CAPS: Mapping[StudyModelName, Decimal] = {
    "sol": Decimal("4.00"), "argon": Decimal("4.00"), "midtier": Decimal("2.00"),
}
STUDY_PLAN_CAPS: Mapping[StudyModelName, Decimal] = {
    "sol": Decimal("26.00"), "argon": Decimal("28.00"), "midtier": Decimal("11.00"),
}
PILOT_REPEATS: Mapping[StudyModelName, int] = {"sol": 2, "argon": 1, "midtier": 1}
STUDY_REPEATS = 5


def manifest_digest(scenario: str) -> str:
    return digest_bytes((PILOT.parent / scenario / "qualification" / "manifest.json").read_bytes())


def image_digest(scenarios: tuple[str, ...]) -> str:
    images: set[str] = {
        json.loads(
            (PILOT.parent / s / "qualification" / "manifest.json").read_bytes()
        )["observed_runtime_image_digest"]
        for s in scenarios
    }
    if len(images) != 1:
        raise ValueError(f"scenarios were qualified on different images: {sorted(images)}")
    return images.pop()


def plan_config(
    name: StudyModelName, cohort: str, scenarios: tuple[str, ...], repeats: int, cap: Decimal,
) -> dict[str, Any]:
    model = next(m for m in STUDY_MODELS if m.name == name)
    data: dict[str, Any] = {
        "scenario_qualifications": [
            {"scenario": s, "manifest_digest": manifest_digest(s)} for s in scenarios
        ],
        "cohort": cohort,
        "route": model.route.model_dump(mode="json"),
        "profile": "openrouter",
        "system_prompt_digest": SYSTEM_PROMPT_SHA256,
        "tool_schemas_digest": ORDERED_TOOL_SCHEMAS_SHA256,
        "image_digest": image_digest(scenarios),
        "envelope": STUDY_ENVELOPE,
        "bounds": ExtensionAgentSettings.for_model(
            model.route.model, envelope=STUDY_ENVELOPE,
        ).model_dump(mode="json"),
        "repeats": repeats,
        "randomization_seed": SEED,
        "dispatch_schedule": "subject-rotated-v1",
        "concurrency": 1,
        "pricing": {"basis": PRICING_BASIS, "conservative_request_bound_usd": None},
        "per_attempt_cap_usd": str(getattr(PER_ATTEMPT_CAPS, name)),
        "total_cap_usd": str(cap),
    }
    RunConfiguration.model_validate(data)
    return data


def library_rerun_config() -> dict[str, Any]:
    """Keep the rerun's eleven library pins; refresh its limits and caps."""
    path = STUDY / "library-rerun-midtier.json"
    data: dict[str, Any] = json.loads(path.read_bytes())
    midtier = next(m for m in STUDY_MODELS if m.name == "midtier")
    data.update(
        envelope=STUDY_ENVELOPE,
        bounds=ExtensionAgentSettings.for_model(
            midtier.route.model, envelope=STUDY_ENVELOPE,
        ).model_dump(mode="json"),
        pricing={"basis": PRICING_BASIS, "conservative_request_bound_usd": None},
        per_attempt_cap_usd=str(PER_ATTEMPT_CAPS.midtier),
        total_cap_usd=str(LIBRARY_RERUN_TOTAL_CAP_USD),
    )
    RunConfiguration.model_validate(data)
    return data


def files() -> dict[str, dict[str, Any]]:
    if sum(PILOT_PLAN_CAPS.values()) != PILOT_TOTAL_CAP_USD:
        raise ValueError("pilot plan caps must add up to the pilot total")
    if sum(STUDY_PLAN_CAPS.values()) != STUDY_TOTAL_CAP_USD:
        raise ValueError("study plan caps must add up to the study total")
    result: dict[str, dict[str, Any]] = {}
    for cohort, scenarios, caps, total in (
        ("pilot", PILOT_SCENARIOS, PILOT_PLAN_CAPS, PILOT_TOTAL_CAP_USD),
        ("study", SCENARIOS, STUDY_PLAN_CAPS, STUDY_TOTAL_CAP_USD),
    ):
        plans = []
        for model in STUDY_MODELS:
            repeats = PILOT_REPEATS[model.name] if cohort == "pilot" else STUDY_REPEATS
            config = f"{cohort}-{model.name}.json"
            result[config] = plan_config(
                model.name, f"fact-shapes-2026-11-{cohort}-{model.name}", scenarios, repeats,
                caps[model.name],
            )
            plans.append({"name": model.name, "config": config})
        result[f"{cohort}.json"] = {
            "cohort": f"fact-shapes-2026-11-{cohort}",
            "combined_cap_usd": str(total),
            "plans": plans,
        }
    result["library-rerun-midtier.json"] = library_rerun_config()
    return result


def render(data: Mapping[str, Any]) -> bytes:
    return (json.dumps(data, indent=2) + "\n").encode()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    check = parser.parse_args().check
    stale = []
    for name, data in files().items():
        path = STUDY / name
        if check:
            if not path.is_file() or path.read_bytes() != render(data):
                stale.append(name)
        else:
            path.write_bytes(render(data))
    if stale:
        raise SystemExit(f"stale cohort files: {', '.join(stale)}")


if __name__ == "__main__":
    main()
