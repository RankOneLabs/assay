import os, tempfile, io, tarfile
from pathlib import Path
from assay_pier_bridge.paths import submission_patch, regular_tree, extract_workspace_archive, ArtifactCollectionRejected
d = Path(tempfile.mkdtemp())
b = d/"b"; f = d/"f"; b.mkdir(); f.mkdir()
(b/"a.txt").write_text("x\n"); (f/"a.txt").write_text("x\n")
open(os.fsencode(str(f)) + b"/bad\xff.txt", "wb").write(b"hi\n")
try:
    regular_tree(f); print("regular_tree ok")
    submission_patch(b, f)
except ArtifactCollectionRejected as e:
    print("typed", e.cause)
except Exception as e:
    print("untyped", type(e).__name__, isinstance(e, ValueError), str(e)[:80])
# hardlink in tar
buf = io.BytesIO()
with tarfile.open(fileobj=buf, mode="w") as t:
    ti = tarfile.TarInfo("./a"); data=b"x"; ti.size=1; t.addfile(ti, io.BytesIO(data))
    ti = tarfile.TarInfo("./b"); ti.type=tarfile.LNKTYPE; ti.linkname="./a"; t.addfile(ti)
r = Path(tempfile.mkdtemp())
try:
    extract_workspace_archive(buf.getvalue(), r)
except ArtifactCollectionRejected as e:
    print("hardlink ->", e.cause)
