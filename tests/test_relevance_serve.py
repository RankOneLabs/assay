"""Tests for serving a label packet: blinding, submission validation, storage."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from assay.investigations.relevance.catalogue import load_catalogue
from assay.investigations.relevance.packet import rubric_card
from assay.investigations.relevance.packet_html import Endpoints, render_packet_html
from assay.investigations.relevance.serve_packet import (
    DRAFT_BACK,
    POST_BACK,
    ServedPacket,
    ServeError,
    load_packet,
    make_server,
    merge_drafts,
    store_labels,
    validate_draft,
    validate_submission,
)

SERVED = Endpoints(labels="/labels", draft="/draft")

CATALOGUE = Path("src/assay/investigations/relevance/catalogues/agent-ops-relevance.v2.yaml")


@pytest.fixture
def questions() -> dict:
    return load_catalogue(CATALOGUE).questions


@pytest.fixture
def packet_file(tmp_path: Path, questions: dict) -> Path:
    document = {
        "format": "assay.label-packet/v1",
        "name": "test-packet",
        "digest": "packet-digest",
        "plan_digest": "plan-digest",
        "cases": [
            {"case_id": 1, "text": "a post by Grafana", "parent_text": None},
            {"case_id": 2, "text": "another post", "parent_text": "a parent"},
        ],
        "rubric": rubric_card(questions),
    }
    path = tmp_path / "packet.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


@pytest.fixture
def packet(packet_file: Path) -> ServedPacket:
    return load_packet(packet_file)


def _labels(**overrides: object) -> dict:
    payload = {
        "format": "assay.label-packet-labels/v1",
        "packet": "test-packet",
        "packet_digest": "packet-digest",
        "plan_digest": "plan-digest",
        "reviewer": "steve",
        "saved_at": "2026-09-18T00:00:00Z",
        "cases": [
            {"case_id": 1, "band": 3, "exclusion": "none", "disposition": "respond", "note": None},
            {"case_id": 2, "band": 2, "exclusion": "none", "disposition": "review", "note": None},
        ],
    }
    return {**payload, **overrides}


# --- the page ---------------------------------------------------------------


def test_default_page_makes_no_network_call(questions: dict) -> None:
    """The property the file:// packet is supposed to have, checked by grep."""
    page = render_packet_html("p", "d", "pd", [{"case_id": 1, "text": "x"}], rubric_card(questions))
    for network in ("fetch(", "XMLHttpRequest", "EventSource", "navigator.sendBeacon"):
        assert network not in page


def test_served_page_posts_to_the_given_urls(questions: dict) -> None:
    page = render_packet_html(
        "p", "d", "pd", [{"case_id": 1, "text": "x"}], rubric_card(questions), endpoints=SERVED
    )
    assert 'const POST_BACK = "/labels"' in page
    assert 'const DRAFT_BACK = "/draft"' in page
    assert "fetch(POST_BACK" in page


def test_served_page_still_hides_the_answer_key_fields(questions: dict) -> None:
    page = render_packet_html(
        "p", "d", "pd", [{"case_id": 1, "text": "x"}], rubric_card(questions), endpoints=SERVED
    )
    for leaked in ("human_label", "production_decision", "stratum", "evaluation_id"):
        assert leaked not in page


def test_load_packet_refuses_a_document_that_is_not_a_packet(tmp_path: Path) -> None:
    path = tmp_path / "other.json"
    path.write_text(json.dumps({"format": "something.else/v1"}), encoding="utf-8")
    with pytest.raises(ServeError, match="not a label packet"):
        load_packet(path)


def test_load_packet_reads_the_case_ids(packet: ServedPacket) -> None:
    assert packet.case_ids == {1, 2}


# --- submission validation --------------------------------------------------


def test_validate_accepts_a_complete_submission(packet: ServedPacket) -> None:
    assert validate_submission(_labels(), packet).case_count == 2


def test_validate_refuses_a_stale_packet_build(packet: ServedPacket) -> None:
    with pytest.raises(ServeError, match="different packet build"):
        validate_submission(_labels(packet_digest="old"), packet)


def test_validate_refuses_a_stale_plan_digest(packet: ServedPacket) -> None:
    with pytest.raises(ServeError, match="plan digest"):
        validate_submission(_labels(plan_digest="old"), packet)


def test_validate_refuses_a_partial_sitting(packet: ServedPacket) -> None:
    labels = _labels()
    labels["cases"] = labels["cases"][:1]
    with pytest.raises(ServeError, match="1 cases unlabelled"):
        validate_submission(labels, packet)


def test_validate_refuses_a_label_for_an_unknown_case(packet: ServedPacket) -> None:
    labels = _labels()
    labels["cases"][0]["case_id"] = 99
    with pytest.raises(ServeError, match="unknown case 99"):
        validate_submission(labels, packet)


def test_validate_refuses_a_duplicated_case(packet: ServedPacket) -> None:
    labels = _labels()
    labels["cases"][1]["case_id"] = 1
    with pytest.raises(ServeError, match="labelled twice"):
        validate_submission(labels, packet)


def test_validate_refuses_a_band_out_of_range(packet: ServedPacket) -> None:
    labels = _labels()
    labels["cases"][0]["band"] = 4
    with pytest.raises(ServeError, match="band out of range"):
        validate_submission(labels, packet)


def test_validate_refuses_an_unknown_exclusion(packet: ServedPacket) -> None:
    labels = _labels()
    labels["cases"][0]["exclusion"] = "not_a_category"
    with pytest.raises(ServeError, match="unknown exclusion"):
        validate_submission(labels, packet)


def test_validate_refuses_an_unknown_disposition(packet: ServedPacket) -> None:
    labels = _labels()
    labels["cases"][0]["disposition"] = "maybe"
    with pytest.raises(ServeError, match="unknown disposition"):
        validate_submission(labels, packet)


def test_validate_refuses_a_missing_disposition(packet: ServedPacket) -> None:
    labels = _labels()
    del labels["cases"][0]["disposition"]
    with pytest.raises(ServeError, match="unknown disposition"):
        validate_submission(labels, packet)


def test_validate_refuses_an_unnamed_reviewer(packet: ServedPacket) -> None:
    with pytest.raises(ServeError, match="no reviewer"):
        validate_submission(_labels(reviewer="  "), packet)


# --- drafts -----------------------------------------------------------------


def _draft(answers: dict, saved_at: str = "2026-09-18T10:00:00Z") -> dict:
    return {
        "format": "assay.label-packet-draft/v1",
        "packet": "test-packet",
        "packet_digest": "packet-digest",
        "plan_digest": "plan-digest",
        "reviewer": "steve",
        "saved_at": saved_at,
        "answers": answers,
    }


def test_draft_accepts_a_case_that_is_only_half_answered(packet: ServedPacket) -> None:
    assert validate_draft(_draft({"1": {"band": 2}}), packet).answered == 0


def test_draft_counts_only_fully_answered_cases(packet: ServedPacket) -> None:
    answers = {
        "1": {"band": 2, "exclusion": "none", "disposition": "review"},
        "2": {"band": 1},
    }
    assert validate_draft(_draft(answers), packet).answered == 1


def test_draft_accepts_an_empty_sitting(packet: ServedPacket) -> None:
    assert validate_draft(_draft({}), packet).answered == 0


def test_draft_refuses_an_unknown_case(packet: ServedPacket) -> None:
    with pytest.raises(ServeError, match="unknown case 99"):
        validate_draft(_draft({"99": {"band": 1}}), packet)


def test_draft_refuses_a_bad_value_even_when_partial(packet: ServedPacket) -> None:
    with pytest.raises(ServeError, match="band out of range"):
        validate_draft(_draft({"1": {"band": 9}}), packet)


def test_draft_refuses_a_stale_packet_build(packet: ServedPacket) -> None:
    payload = _draft({})
    payload["packet_digest"] = "old"
    with pytest.raises(ServeError, match="different packet build"):
        validate_draft(payload, packet)


def test_merge_keeps_a_case_the_incoming_draft_never_saw() -> None:
    """The load-bearing one: a device holding a subset must not delete work."""
    stored = _draft({"1": {"band": 3}, "2": {"band": 1}}, "2026-09-18T10:00:00Z")
    incoming = _draft({"1": {"band": 3}}, "2026-09-18T11:00:00Z")
    assert set(merge_drafts(stored, incoming)["answers"]) == {"1", "2"}


def test_merge_takes_the_later_edit_on_a_conflict() -> None:
    stored = _draft({"1": {"band": 0}}, "2026-09-18T10:00:00Z")
    incoming = _draft({"1": {"band": 3}}, "2026-09-18T11:00:00Z")
    assert merge_drafts(stored, incoming)["answers"]["1"]["band"] == 3


def test_merge_keeps_the_stored_edit_when_the_incoming_is_older() -> None:
    stored = _draft({"1": {"band": 3}}, "2026-09-18T11:00:00Z")
    incoming = _draft({"1": {"band": 0}}, "2026-09-18T10:00:00Z")
    assert merge_drafts(stored, incoming)["answers"]["1"]["band"] == 3


def test_merge_onto_nothing_is_the_incoming_draft() -> None:
    incoming = _draft({"1": {"band": 3}})
    assert merge_drafts(None, incoming) == incoming


# --- storage ----------------------------------------------------------------


def test_store_labels_writes_the_stable_path(tmp_path: Path) -> None:
    path = store_labels(_labels(), tmp_path / "labels.json")
    assert json.loads(path.read_text(encoding="utf-8"))["reviewer"] == "steve"


def test_store_labels_moves_an_earlier_sitting_aside(tmp_path: Path) -> None:
    output = tmp_path / "labels.json"
    store_labels(_labels(reviewer="first"), output)
    store_labels(_labels(reviewer="second"), output)
    kept = [p for p in tmp_path.glob("labels-*.json")]
    assert json.loads(output.read_text(encoding="utf-8"))["reviewer"] == "second"
    assert len(kept) == 1
    assert json.loads(kept[0].read_text(encoding="utf-8"))["reviewer"] == "first"


# --- the server -------------------------------------------------------------


@pytest.fixture
def running(packet: ServedPacket, tmp_path: Path):
    output = tmp_path / "out" / "labels.json"
    server = make_server(packet, output, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[0], server.server_address[1]
    yield f"http://{host}:{port}", output
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def _post(url: str, payload: dict) -> tuple[int, str]:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"content-type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def test_server_serves_the_packet_page(running: tuple[str, Path]) -> None:
    base, _ = running
    with urllib.request.urlopen(f"{base}/", timeout=5) as response:
        assert "a post by Grafana" in response.read().decode()


def test_server_serves_no_path_but_the_page(running: tuple[str, Path]) -> None:
    base, _ = running
    for path in ("/answer-key-private.json", "/packet.json", "/../packet.json"):
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(f"{base}{path}", timeout=5)
        assert caught.value.code == 404


def test_server_stores_an_accepted_submission(running: tuple[str, Path]) -> None:
    base, output = running
    status, body = _post(f"{base}{POST_BACK}", _labels())
    assert status == 200
    assert "saved 2 cases" in body
    assert json.loads(output.read_text(encoding="utf-8"))["reviewer"] == "steve"


def test_server_refuses_a_stale_submission_without_writing(running: tuple[str, Path]) -> None:
    base, output = running
    status, body = _post(f"{base}{POST_BACK}", _labels(packet_digest="old"))
    assert status == 400
    assert "different packet build" in body
    assert not output.exists()


def test_server_has_no_draft_before_one_is_synced(running: tuple[str, Path]) -> None:
    base, _ = running
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(f"{base}{DRAFT_BACK}", timeout=5)
    assert caught.value.code == 404


def test_server_round_trips_a_draft_between_devices(running: tuple[str, Path]) -> None:
    """One device syncs a partial draft; another reads it back and adds to it."""
    base, _ = running
    first = _post(f"{base}{DRAFT_BACK}", _draft({"1": {"band": 3}}, "2026-09-18T10:00:00Z"))
    assert first[0] == 200

    with urllib.request.urlopen(f"{base}{DRAFT_BACK}", timeout=5) as response:
        assert set(json.load(response)["answers"]) == {"1"}

    _post(f"{base}{DRAFT_BACK}", _draft({"2": {"band": 1}}, "2026-09-18T11:00:00Z"))
    with urllib.request.urlopen(f"{base}{DRAFT_BACK}", timeout=5) as response:
        assert set(json.load(response)["answers"]) == {"1", "2"}


def test_a_synced_draft_never_becomes_the_scored_labels(running: tuple[str, Path]) -> None:
    """Draft and submission are separate artifacts; only `/labels` writes one."""
    base, output = running
    _post(f"{base}{DRAFT_BACK}", _draft({"1": {"band": 3}}))
    assert not output.exists()
    assert output.with_name("draft.json").exists()
