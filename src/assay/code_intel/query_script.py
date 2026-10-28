"""Dependency-free source passed to ``python -c`` inside the tool container."""

QUERY_SCRIPT = r'''
import hashlib
import json
import sys
import time
from pathlib import Path

started = time.perf_counter()
index_file, kind, text, token_budget = sys.argv[1:]
manifest = json.loads(Path(index_file).read_text(encoding="utf-8"))
needle = text.strip().casefold()
if not needle or kind not in ("symbol", "references"):
    sys.stderr.write("query kind and non-empty text are required\n")
    sys.exit(2)
if kind == "symbol":
    found = [item for item in manifest["items"]
             if item.get("symbol") and needle in item["symbol"].casefold()]
    found.sort(key=lambda item: (
        item["symbol"].casefold() != needle, item["file_path"],
        item.get("start_line") or 0,
    ))
else:
    references = [item for item in manifest["references"]
                  if needle in item["name"].casefold()]
    references.sort(key=lambda item: (item["name"].casefold() != needle,
                                      item["file_path"], item["line"], item["column"]))
    empty_hash = "sha256:" + hashlib.sha256(b"").hexdigest()
    found = [{
        "repo_revision": manifest["repo_revision"],
        "file_path": item["file_path"], "start_line": item["line"],
        "end_line": item["line"], "symbol": item["name"],
        "retrieval_method": "typescript_reference", "rank": rank,
        "content_hash": empty_hash, "approximate_tokens": 0,
        "raw_source_ref": f'{item["file_path"]}:{item["line"]}:{item["line"]}',
        "content": None,
    } for rank, item in enumerate(references)]
result = {"query_kind": kind, "items": [], "latency_ms": 0.0,
          "supplied_tokens": 0, "snippets": []}
budget = int(token_budget) * 4
for item in found[:20]:
    item = {**item, "rank": len(result["items"])}
    candidate = {
        **result, "items": [*result["items"], item],
        "supplied_tokens": result["supplied_tokens"] + item["approximate_tokens"],
        "snippets": [*result["snippets"], item.get("content") or ""],
    }
    if len(json.dumps(candidate, separators=(",", ":")).encode("utf-8")) > budget:
        break
    result = candidate
result["latency_ms"] = (time.perf_counter() - started) * 1000
print(json.dumps(result, separators=(",", ":")))
'''
