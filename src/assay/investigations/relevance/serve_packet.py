"""Serve a blind label packet on the tailnet and accept the labels back.

The packet page is a single self-contained file, so labelling at a desk needs no
server at all. Labelling on a phone does: the download lands on the phone, and
getting it back to the workstation is the whole friction. This serves the page
and takes a POST of the finished labels straight into the receipts directory.

Two properties the design holds onto:

*   **The answer key cannot leak.** Nothing here serves a directory. The page is
    rendered into memory at startup from ``packet.json`` and returned from that
    string; every other path is a 404. A misaimed ``--directory`` cannot expose
    ``answer-key-private.json`` because there is no ``--directory``.
*   **A submission is checked before it lands.** The payload must carry the
    packet and plan digests it was collected under and cover exactly the packet's
    cases, so a stale tab from an earlier build cannot silently overwrite a good
    sitting.

Bind defaults to loopback. The packet carries real post text, so putting it on a
wider interface is a deliberate act: pass the tailnet address explicitly.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from assay.investigations.relevance.packet import BAND_NAMES, DISPOSITIONS
from assay.investigations.relevance.packet_html import Endpoints, render_packet_html

#: Where a finished sitting is submitted.
POST_BACK = "/labels"

#: Where the partial draft is synced. Separate from ``POST_BACK`` on purpose: a
#: draft is scratch and may be incomplete, while ``labels.json`` is the artifact
#: the scorer reads and ``PLAN.md`` pre-registers against. Nothing half-finished
#: may reach that file.
DRAFT_BACK = "/draft"

#: What the server keeps between sittings.
DRAFT_FILE = "draft.json"

#: The endpoints a served page is rendered against.
SERVED_ENDPOINTS = Endpoints(labels=POST_BACK, draft=DRAFT_BACK)

#: Cap on a submitted body. The largest honest payload is 79 cases of three
#: choices plus notes; a megabyte is orders of magnitude of headroom and still
#: refuses to buffer something absurd.
MAX_BODY_BYTES = 1_000_000


class ServeError(RuntimeError):
    """A packet could not be served, or a submission could not be accepted."""


@dataclass(frozen=True, slots=True)
class ServedPacket:
    """Everything the server needs, read once at startup."""

    name: str
    digest: str
    plan_digest: str
    case_ids: frozenset[int]
    exclusions: frozenset[str]
    page: str


@dataclass(frozen=True, slots=True)
class Submission:
    """An accepted label set."""

    reviewer: str
    saved_at: str
    case_count: int


@dataclass(frozen=True, slots=True)
class Draft:
    """An accepted partial draft."""

    reviewer: str
    saved_at: str
    answered: int


def load_packet(path: Path, *, endpoints: Endpoints = SERVED_ENDPOINTS) -> ServedPacket:
    """Read a built ``packet.json`` and render its page against the endpoints."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("format") != "assay.label-packet/v1":
        raise ServeError(f"{path} is not a label packet")
    cases = document["cases"]
    rubric = document["rubric"]
    return ServedPacket(
        name=document["name"],
        digest=document["digest"],
        plan_digest=document["plan_digest"],
        case_ids=frozenset(int(case["case_id"]) for case in cases),
        exclusions=frozenset(option["name"] for option in rubric["exclusion"]["options"]),
        page=render_packet_html(
            document["name"],
            document["digest"],
            document["plan_digest"],
            cases,
            rubric,
            endpoints=endpoints,
        ),
    )


def _validate_answer(
    case_id: int, entry: Mapping[str, Any], packet: ServedPacket, *, partial: bool
) -> None:
    """Check one case's answers. ``partial`` allows a field to be unanswered yet."""

    def given(name: str) -> bool:
        """A draft may leave a field unanswered; a submission may not."""
        return not (partial and entry.get(name) is None)

    band = entry.get("band")
    if given("band") and (not isinstance(band, int) or not 0 <= band < len(BAND_NAMES)):
        raise ServeError(f"case {case_id}: band out of range")
    exclusion = entry.get("exclusion")
    if given("exclusion") and exclusion not in packet.exclusions:
        raise ServeError(f"case {case_id}: unknown exclusion {exclusion!r}")
    disposition = entry.get("disposition")
    if given("disposition") and disposition not in {name for name, _ in DISPOSITIONS}:
        raise ServeError(f"case {case_id}: unknown disposition {disposition!r}")


def _check_provenance(payload: Mapping[str, Any], packet: ServedPacket, fmt: str) -> None:
    if payload.get("format") != fmt:
        raise ServeError(f"not a {fmt.rsplit('.', 1)[-1]} payload")
    if payload.get("packet_digest") != packet.digest:
        raise ServeError("labels were collected under a different packet build")
    if payload.get("plan_digest") != packet.plan_digest:
        raise ServeError("labels do not carry the plan digest they were collected under")


def validate_draft(payload: Mapping[str, Any], packet: ServedPacket) -> Draft:
    """Check a partial draft. Unlike a submission, incompleteness is the norm."""
    _check_provenance(payload, packet, "assay.label-packet-draft/v1")
    answers = payload.get("answers")
    if not isinstance(answers, Mapping):
        raise ServeError("answers must be an object")
    answered = 0
    for key, entry in answers.items():
        case_id = int(key)
        if case_id not in packet.case_ids:
            raise ServeError(f"draft for unknown case {case_id}")
        if not isinstance(entry, Mapping):
            raise ServeError(f"case {case_id}: answers must be an object")
        _validate_answer(case_id, entry, packet, partial=True)
        if all(entry.get(field) is not None for field in ("band", "exclusion", "disposition")):
            answered += 1
    return Draft(
        reviewer=str(payload.get("reviewer") or "unknown"),
        saved_at=str(payload.get("saved_at") or ""),
        answered=answered,
    )


def merge_drafts(stored: Mapping[str, Any] | None, incoming: Mapping[str, Any]) -> dict[str, Any]:
    """Union the two, the later ``saved_at`` winning a case answered on both.

    The merge happens here and not only in the browser so that a device which
    failed its load-time fetch — and therefore holds a subset — cannot delete
    another device's work by syncing. A draft only ever grows.
    """
    if stored is None:
        return dict(incoming)
    incoming_newer = str(incoming.get("saved_at") or "") >= str(stored.get("saved_at") or "")
    merged: dict[str, Any] = dict(stored.get("answers") or {})
    for key, entry in (incoming.get("answers") or {}).items():
        if key not in merged or not merged[key] or incoming_newer:
            merged[key] = entry
    newer = incoming if incoming_newer else stored
    return {**newer, "answers": merged}


def store_draft(payload: Mapping[str, Any], path: Path) -> dict[str, Any]:
    """Merge a synced draft into the stored one and write it back."""
    stored = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    merged = merge_drafts(stored, payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return merged


def validate_submission(payload: Mapping[str, Any], packet: ServedPacket) -> Submission:
    """Check a posted label set against the packet it claims to answer.

    Rejects rather than repairs. A submission that does not match is far more
    likely to be a stale tab than a near-miss worth salvaging.
    """
    _check_provenance(payload, packet, "assay.label-packet-labels/v1")

    reviewer = str(payload.get("reviewer") or "").strip()
    if not reviewer:
        raise ServeError("no reviewer name")

    entries = payload.get("cases")
    if not isinstance(entries, list):
        raise ServeError("cases must be a list")

    seen: set[int] = set()
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ServeError("each case must be an object")
        case_id = int(entry.get("case_id", -1))
        if case_id not in packet.case_ids:
            raise ServeError(f"label for unknown case {case_id}")
        if case_id in seen:
            raise ServeError(f"case {case_id} labelled twice")
        seen.add(case_id)
        _validate_answer(case_id, entry, packet, partial=False)

    missing = packet.case_ids - seen
    if missing:
        raise ServeError(f"{len(missing)} cases unlabelled: {sorted(missing)[:5]}")

    return Submission(
        reviewer=reviewer,
        saved_at=str(payload.get("saved_at") or ""),
        case_count=len(seen),
    )


def store_labels(payload: Mapping[str, Any], output: Path) -> Path:
    """Write labels to ``output``, moving any existing file aside first.

    Resubmitting is normal — a reviewer changes their mind about a case and
    presses the button again — so the path stays stable for the scorer while no
    earlier sitting is ever destroyed.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        stamp = datetime.fromtimestamp(output.stat().st_mtime, UTC).strftime("%Y%m%dT%H%M%SZ")
        output.replace(output.with_name(f"{output.stem}-{stamp}{output.suffix}"))
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def _handler(packet: ServedPacket, output: Path) -> type[BaseHTTPRequestHandler]:
    draft_path = output.with_name(DRAFT_FILE)

    class PacketHandler(BaseHTTPRequestHandler):
        server_version = "assay-label-packet/1.0"

        def _send(self, status: HTTPStatus, body: str, content_type: str) -> None:
            encoded = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's contract
            if self.path in ("/", "/packet.html"):
                self._send(HTTPStatus.OK, packet.page, "text/html")
                return
            if self.path == DRAFT_BACK:
                if not draft_path.exists():
                    self._send(HTTPStatus.NOT_FOUND, "no draft yet\n", "text/plain")
                    return
                self._send(
                    HTTPStatus.OK, draft_path.read_text(encoding="utf-8"), "application/json"
                )
                return
            self._send(HTTPStatus.NOT_FOUND, "no such path\n", "text/plain")

        def _body(self) -> Any:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY_BYTES:
                raise ServeError("bad body length")
            return json.loads(self.rfile.read(length))

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's contract
            if self.path not in (POST_BACK, DRAFT_BACK):
                self._send(HTTPStatus.NOT_FOUND, "no such path\n", "text/plain")
                return
            is_draft = self.path == DRAFT_BACK
            try:
                payload = self._body()
                if is_draft:
                    draft = validate_draft(payload, packet)
                else:
                    submission = validate_submission(payload, packet)
            except (ValueError, ServeError) as error:
                print(f"  refused: {error}", flush=True)
                self._send(HTTPStatus.BAD_REQUEST, f"{error}\n", "text/plain")
                return

            if is_draft:
                merged = store_draft(payload, draft_path)
                total = len(merged.get("answers") or {})
                print(f"  draft {draft.answered} complete of {total} touched", flush=True)
                self._send(HTTPStatus.OK, f"draft saved ({draft.answered})\n", "text/plain")
                return

            path = store_labels(payload, output)
            print(
                f"  accepted {submission.case_count} cases from {submission.reviewer} -> {path}",
                flush=True,
            )
            self._send(
                HTTPStatus.OK,
                f"saved {submission.case_count} cases to {path.name}\n",
                "text/plain",
            )

        def log_message(self, format: str, *args: Any) -> None:
            print(f"{self.address_string()} {format % args}", flush=True)

    return PacketHandler


def make_server(packet: ServedPacket, output: Path, host: str, port: int) -> ThreadingHTTPServer:
    """Bind a server without running it, so a test can drive it over a real socket."""
    return ThreadingHTTPServer((host, port), _handler(packet, output))


def serve(packet: ServedPacket, output: Path, host: str, port: int) -> None:
    """Run until interrupted. The IO boundary; everything above it is testable."""
    server = make_server(packet, output, host, port)
    print(f"{packet.name}: {len(packet.case_ids)} cases", flush=True)
    print(f"  http://{host}:{port}/  ->  labels land in {output}", flush=True)
    print(f"  draft syncs to {output.with_name(DRAFT_FILE)}", flush=True)
    print("  ctrl-c to stop", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve a blind label packet and take labels back.")
    parser.add_argument("--packet", type=Path, required=True, help="a built packet.json")
    parser.add_argument("--output", type=Path, required=True, help="where labels.json is written")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: loopback)")
    parser.add_argument("--port", type=int, default=8099)
    args = parser.parse_args()
    serve(load_packet(args.packet), args.output, args.host, args.port)


if __name__ == "__main__":
    main()
