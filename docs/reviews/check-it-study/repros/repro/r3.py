import os, tempfile, threading
from pathlib import Path
from assay_pier_bridge.paths import collect_artifacts, ArtifactCollectionRejected
w = Path(tempfile.mkdtemp()); sub = w/"submission"; sub.mkdir()
(w/"env").write_text("OPENROUTER_API_KEY=sk-secret\n")
stop = False
def swapper():
    p = sub/"trajectory.json"
    while not stop:
        try:
            p.write_text("{}"); os.unlink(p); os.symlink("../env", p); os.unlink(p)
        except OSError: pass
t = threading.Thread(target=swapper); t.start()
hits = 0
for _ in range(20000):
    try:
        a = collect_artifacts(sub, max_bytes=8_000_000, max_aggregate_bytes=32_000_000, max_entries=4096, aggregate_exempt_path="manifest.json")
    except (ArtifactCollectionRejected, FileNotFoundError):
        continue
    if b"sk-secret" in a.get("trajectory.json", b""):
        hits += 1
stop = True; t.join()
print("leaks:", hits)
