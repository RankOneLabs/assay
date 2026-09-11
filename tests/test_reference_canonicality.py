from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_review_round2 import _rewrite, _run

from assay.canonical import canonical_json
from assay.references import reference_closure
from assay.store import ObjectStore, verification_session
from assay.verify import export_bundle, verify_bundle, verify_manifest

NONCANONICAL = [
    pytest.param(
        b'{"assay_object_refs":[],"assay_object_refs":["REF"]}', id="duplicate-keys"
    ),
    pytest.param(b'{"assay_object_refs":["REF"],"value":NaN}', id="nan"),
    pytest.param(b'{"assay_object_refs":["REF"],"value":Infinity}', id="infinity"),
    pytest.param(b'{"assay_object_refs":["REF"],"value":-Infinity}', id="negative-infinity"),
    pytest.param(b'{ "assay_object_refs": ["REF"] }', id="whitespace"),
    pytest.param(b'{"z":0,"assay_object_refs":["REF"]}', id="key-order"),
    pytest.param(b'{"value":1,"value":2}', id="duplicate-without-edges"),
    pytest.param('{"assay_object_refs":["REF"]}'.encode("utf-16"), id="utf16"),
]


def _data(template: bytes, leaf: str) -> bytes:
    if template.startswith(b"\xff\xfe") or template.startswith(b"\xfe\xff"):
        return template.decode("utf-16").replace("REF", leaf).encode("utf-16")
    return template.replace(b"REF", leaf.encode())


@pytest.mark.parametrize("template", NONCANONICAL)
def test_noncanonical_extension_never_contributes_cached_edges(
    tmp_path: Path, template: bytes
) -> None:
    store = ObjectStore(tmp_path)
    leaf = str(store.publish_bytes(b"binary leaf"))
    bad = str(store.publish_bytes(_data(template, leaf)))
    root = str(store.publish_json({"assay_object_refs": [bad]}))
    session = verification_session(store)
    for _ in range(2):
        with pytest.raises(ValueError, match="noncanonical JSON|non-finite"):
            reference_closure(session, (root,))
        assert (bad, "data") not in session.edges
        assert leaf not in session.cache


@pytest.mark.parametrize("template", NONCANONICAL)
async def test_noncanonical_extension_rejected_by_verification_and_export(
    tmp_path: Path, template: bytes
) -> None:
    store = ObjectStore(tmp_path / "source")
    result = await _run(store)
    leaf = str(store.publish_bytes(b"binary leaf"))
    bad = str(store.publish_bytes(_data(template, leaf)))
    key, ref = next(iter(result.manifest.evaluation_records.items()))
    record = json.loads(store.read_bytes(ref))
    record["source_references"].append(bad)
    root = _rewrite(store, result, "evaluation_records", key, record)
    for verify in (verify_manifest, verify_bundle):
        failures = verify(store, root)
        assert any(
            "noncanonical JSON" in f.message or "non-finite" in f.message for f in failures
        ), failures
    destination = tmp_path / "export"
    with pytest.raises(ValueError, match="invalid root"):
        export_bundle(store, root, destination)
    assert not destination.exists()


@pytest.mark.parametrize("data", [b"binary leaf", b"\xff\x00", b'{"truncated":'])
async def test_canonical_json_extensions_and_non_json_leaves_still_export(
    tmp_path: Path, data: bytes
) -> None:
    store = ObjectStore(tmp_path / "source")
    result = await _run(store)
    leaf = str(store.publish_bytes(data))
    extension = str(store.publish_bytes(canonical_json({"assay_object_refs": [leaf]})))
    key, ref = next(iter(result.manifest.evaluation_records.items()))
    record = json.loads(store.read_bytes(ref))
    record["source_references"].append(extension)
    root = _rewrite(store, result, "evaluation_records", key, record)
    assert {extension, leaf} <= reference_closure(store, (root,))
    assert verify_manifest(store, root) == ()
    bundle = export_bundle(store, root, tmp_path / "export")
    assert verify_bundle(bundle, root) == ()
    assert bundle.read_bytes(leaf) == data
