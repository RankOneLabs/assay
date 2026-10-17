import sys, tempfile
from pathlib import Path
sys.path.insert(0, "tests")
from test_execution import execution_fixture
from test_execution_safety import _ceiling_plan
from assay.canonical import digest_bytes
from assay.review.index import classify_object
from assay.store import ObjectStore
f = execution_fixture(ObjectStore(Path(tempfile.mkdtemp())), subject_ids=("a",), worker_repeats=1)
b = _ceiling_plan(f, max_cells=2, max_wall_time_seconds=30, max_fleet_occupancy=1)
print(classify_object(digest_bytes(b), b))
