"""Join census labels to their answer key so scoring can cross-walk on `evaluation_id`.

A packet's `labels.json` is keyed by `case_id`, which is local to one sitting and
means nothing across packets. `evaluation_id` is the stable identity, and it lives
only in that packet's private answer key. `score --census` cross-walks `substance`
against `band` and so needs the census labels carrying it.

The join is deliberately strict: a `case_id` in the labels with no row in the key,
or a count mismatch, is an error rather than a silently short cross-walk.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from assay.investigations.relevance.packet import BAND_NAMES


class MergeError(Exception):
    """The labels and the answer key do not describe the same packet."""


def band_name(raw: Any) -> str:
    """The census stores `band` as its rubric index; scoring compares by name.

    `packet.py` builds the census rubric as `BAND_NAMES[index]`, so the index is
    the name's position and nothing else. Converting here rather than in the
    scorer keeps the adapter in the join, where the two formats already meet.
    """
    if isinstance(raw, str) and not raw.isdigit():
        if raw not in BAND_NAMES:
            raise MergeError(f"unknown band {raw!r}")
        return raw
    index = int(raw)
    if not 0 <= index < len(BAND_NAMES):
        raise MergeError(f"band index {index} outside 0..{len(BAND_NAMES) - 1}")
    return BAND_NAMES[index]


def merge_census(
    labels: Mapping[str, Any], key: Mapping[str, Any]
) -> dict[str, Any]:
    """Return the census labels with `evaluation_id` attached to every case."""
    if labels.get("packet_digest") != key.get("digest"):
        raise MergeError(
            f"digest mismatch: labels {labels.get('packet_digest')!r} "
            f"vs key {key.get('digest')!r}"
        )
    evaluation_of = {int(case["case_id"]): int(case["evaluation_id"]) for case in key["cases"]}
    cases: Sequence[Mapping[str, Any]] = labels["cases"]
    missing = [case["case_id"] for case in cases if int(case["case_id"]) not in evaluation_of]
    if missing:
        raise MergeError(f"no answer-key row for case_id {missing}")
    if len(cases) != len(evaluation_of):
        raise MergeError(f"{len(cases)} labelled cases against {len(evaluation_of)} in the key")
    return {
        **labels,
        "cases": [
            {
                **case,
                "evaluation_id": evaluation_of[int(case["case_id"])],
                "band": band_name(case["band"]),
            }
            for case in cases
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, required=True, help="a packet's labels.json")
    parser.add_argument("--key", type=Path, required=True, help="that packet's answer key")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    merged = merge_census(
        json.loads(args.labels.read_text(encoding="utf-8")),
        json.loads(args.key.read_text(encoding="utf-8")),
    )
    args.output.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    print(f"merged {len(merged['cases'])} cases -> {args.output}")


if __name__ == "__main__":
    main()
