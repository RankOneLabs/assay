"""Tests for the round 4 packet: recency selection from fresh exports and the v4 form."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typesafe_relevance.catalogue import load_catalogue
from typesafe_relevance.packet import PacketError, select_fresh
from typesafe_relevance.run_packet import FRESH_TAKE, build_fresh

V4 = Path(__file__).resolve().parent / "fixtures/label-form.yaml"


def _record(evaluation_id: int, decision: bool = True) -> dict:
    return {
        "evaluation_id": evaluation_id,
        "platform": "bluesky",
        "channel": None,
        "url": f"https://example.test/{evaluation_id}",
        # Letters, not digits: text differing only by a number counts as repeated.
        "text": "post " + "".join(chr(ord("a") + int(d)) for d in str(evaluation_id)),
        "parent_author_name": None,
        "parent_text": None,
        "author_name": "someone",
        "author_handle": "someone.test",
        "snapshot_id": None,
        "human_label": None,
        "production_score": 0.7,
        "production_decision": decision,
    }


def _populations() -> dict[str, dict[int, dict]]:
    return {
        "agent-ops": {e: _record(e) for e in range(1000, 1100)},
        "agent-evals": {e: _record(e, decision=False) for e in range(2000, 2050)},
    }


def test_select_fresh_takes_the_most_recent_per_project() -> None:
    packet = select_fresh(
        {"a": list(range(10)), "b": list(range(100, 110))}, "p", "seed", [("a", 3), ("b", 2)]
    )
    by_stratum = {
        key: sorted(c.evaluation_id for c in packet.cases if c.stratum == key) for key in "ab"
    }
    assert by_stratum == {"a": [7, 8, 9], "b": [108, 109]}


def test_select_fresh_skips_earlier_rounds() -> None:
    packet = select_fresh(
        {"a": list(range(10))}, "p", "seed", [("a", 3)], exclude=frozenset({9, 7})
    )
    assert sorted(c.evaluation_id for c in packet.cases) == [5, 6, 8]


def test_select_fresh_refuses_a_project_that_is_too_small() -> None:
    with pytest.raises(PacketError, match="has 2 fresh evaluations, need 3"):
        select_fresh({"a": [1, 2]}, "p", "seed", [("a", 3)])


def test_case_ids_are_display_order_and_mix_the_projects() -> None:
    packet = select_fresh(
        {"a": list(range(50)), "b": list(range(100, 150))}, "p", "seed", [("a", 20), ("b", 20)]
    )
    assert [c.case_id for c in packet.cases] == list(range(1, 41))
    first_half = {c.stratum for c in packet.cases[:20]}
    assert first_half == {"a", "b"}


def test_build_fresh_writes_a_blind_v4_packet(tmp_path: Path) -> None:
    questions = load_catalogue(V4).questions
    build_fresh(_populations(), questions, tmp_path, sitting="one")

    packet = json.loads((tmp_path / "packet.json").read_text(encoding="utf-8"))
    assert len(packet["cases"]) == sum(n for _, n in FRESH_TAKE)
    assert [q["key"] for q in packet["rubric"]] == ["exclusion", "substance", "needs_thread"]
    blind = json.dumps(packet["cases"])
    for leak in ("production", "someone", "example.test"):
        assert leak not in blind
    assert "assay.label-packet-labels/v3" in (tmp_path / "packet.html").read_text(
        encoding="utf-8"
    )


def test_build_fresh_keys_production_by_case(tmp_path: Path) -> None:
    build_fresh(_populations(), load_catalogue(V4).questions, tmp_path, sitting="one")
    key = json.loads((tmp_path / "answer-key-private.json").read_text(encoding="utf-8"))

    ops = [c for c in key["cases"] if c["project_key"] == "agent-ops"]
    evals = [c for c in key["cases"] if c["project_key"] == "agent-evals"]
    assert (len(ops), len(evals)) == (65, 35)
    assert min(c["evaluation_id"] for c in ops) == 1035
    assert all(c["production_decision"] for c in ops)
    assert not any(c["production_decision"] for c in evals)


def test_build_fresh_takes_repeated_text_once_and_skips_earlier_rounds(tmp_path: Path) -> None:
    populations = _populations()
    populations["agent-ops"][1099]["text"] = "📦 relay v0.9.2 — https://example.test/a"
    populations["agent-ops"][1098]["text"] = "📦 Relay v0.9.1 https://example.test/b"
    populations["agent-ops"][1097]["text"] = "seen before"
    populations["agent-ops"][1000]["text"] = "Seen before!"
    build_fresh(
        populations,
        load_catalogue(V4).questions,
        tmp_path,
        sitting="one",
        exclude=frozenset({1000}),
    )
    key = json.loads((tmp_path / "answer-key-private.json").read_text(encoding="utf-8"))
    ids = {c["evaluation_id"] for c in key["cases"]}
    assert 1099 in ids
    assert not ids & {1098, 1097}
    assert key["excluded_repeated_text"] == 2
