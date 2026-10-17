import asyncio, json, sys, tempfile
from decimal import Decimal
from pathlib import Path
sys.path.insert(0, "tests")
from test_execution import FakeWorker, execution_fixture
from test_execution_safety import _ceiling_plan
from assay.canonical import digest_bytes
from assay.execution import AdmissionLedger, WorkerSuccess, execute_plan
from assay.store import ObjectStore

async def main():
    tmp = Path(tempfile.mkdtemp())
    fixture = execution_fixture(ObjectStore(tmp), subject_ids=("a", "b"), worker_repeats=1,
                                concurrency=2) if False else execution_fixture(ObjectStore(tmp), subject_ids=("a", "b"), worker_repeats=1)
    fixture.arguments["concurrency"] = fixture.arguments.get("concurrency", 4)
    plan_bytes = _ceiling_plan(fixture, max_cells=2, max_wall_time_seconds=30, max_fleet_occupancy=2)
    order = []
    class W(FakeWorker):
        supports_run_admission = True
        def __init__(self, ledger=None): self.ledger = ledger
        def bind_admission(self, ledger):
            ledger.configure_requests(max_requests=100, max_spend_usd=Decimal(0), request_cost_bound_usd=Decimal(0))
            return W(ledger)
        async def run(self, **kw):
            order.append(len(order))
            me = len(order)
            r = self.ledger.reserve("request")
            if r is not None: raise r
            if me == 2:
                await asyncio.sleep(0.2)   # slow multi-turn cell, admitted
                r = self.ledger.reserve("request")
                if r is not None: raise r
            return WorkerSuccess({"score": 1})
    res = await execute_plan(**{**fixture.arguments, "plan_bytes": plan_bytes,
        "authorization": digest_bytes(plan_bytes),
        "workers": {arm.id: W() for arm in fixture.snapshot.arms}})
    print(type(res).__name__, getattr(res, "error_type", None))
    for ref in res.manifest.execution_records.values():
        o = json.loads(fixture.store.read_bytes(ref)); print(o["coordinate"]["id"] if "id" in o["coordinate"] else o["coordinate"], o["status"], o["error_type"])
asyncio.run(main())
