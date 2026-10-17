import tempfile
from pathlib import Path
from assay_pier_bridge.paths import submission_patch
d = Path(tempfile.mkdtemp())
b = d/"b"; f = d/"f"; (b/"lib").mkdir(parents=True); f.mkdir()
(b/"lib"/"x.ts").write_text("x\n"); (f/"lib").write_text("now a file\n")
try:
    p = submission_patch(b, f); print("ok", len(p.patch))
except Exception as e:
    print(type(e).__name__, e)
