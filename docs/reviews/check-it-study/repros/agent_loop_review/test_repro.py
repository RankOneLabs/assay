import json, sys
from pathlib import Path
sys.path.insert(0, "integrations/pier/tests")
import pytest
from test_agent_loop import _local, _pilot, Scripted, FakeSandbox, _call, _reset_sandboxes  # noqa
from assay_pier_bridge.agent_loop import AgentLoopError, ModelTurn
from assay_pier_bridge.identity import canonical_json


def raw_call(name, raw, turn):
    return {"id": f"call-{turn}", "type": "function", "function": {"name": name, "arguments": raw}}


def test_lone_surrogate(tmp_path):
    completion = Scripted([raw_call("write_file", '{"path":"a.txt","content":"x\\ud800"}', 1)])
    with pytest.raises(AgentLoopError) as e:
        _local(tmp_path, completion).run_cell(cell_id="s:a:w0", package={"instruction.md": "Edit", "workspace/a.txt": "o\n"})
    print("CAUSE:", e.value.cause)
    try:
        canonical_json(e.value.trajectory)
    except Exception as err:
        print("TRAJECTORY SERIALIZATION FAILS:", type(err).__name__, err)


def test_submit_after_cap(tmp_path):
    calls = [_call("read_file", {"path": "src/a.ts", "start_line": None, "end_line": None}, i) for i in range(15)]
    for i, c in enumerate(calls):
        c["id"] = f"c{i}"
    completion = Scripted(calls, [_call("submit_output", {"title": "t", "body": "b"}, 99)])
    with pytest.raises(AgentLoopError) as e:
        _pilot(tmp_path, completion).run_cell(cell_id="s:a:w0", package={"instruction.md": "Edit", "workspace/src/a.ts": "o\n"})
    print("CAUSE after 15 calls then submit:", e.value.cause)


def test_observation_override(tmp_path):
    class C(Scripted):
        def __call__(self, **kw):
            t = super().__call__(**kw)
            return ModelTurn(t.message, t.finish_reason, 7, 3, None, observations={"prompt_tokens": 0, "kind": "x"})
    completion = C([_call("submit_output", {"summary": "s"}, 1)])
    r = _local(tmp_path, completion).run_cell(cell_id="s:a:w0", package={"instruction.md": "Edit", "workspace/a.txt": "o\n"})
    print([e for e in r.trajectory["events"] if e.get("turn") == 1])


def test_truncation_drops_assistant_prose(tmp_path):
    turns = [[_call("run_command", {"command": "echo"}, i)] for i in range(1, 6)]
    turns.append([_call("submit_output", {"summary": "s"}, 6)])
    completion = Scripted(*turns, content="REASONING-MARKER")
    from assay_pier_bridge.agent_loop import LoopBounds
    r = _local(tmp_path, completion, bounds=LoopBounds(max_conversation_bytes=1200)).run_cell(
        cell_id="s:a:w0", package={"instruction.md": "Edit"})
    blob = json.dumps(r.trajectory)
    print("model turns:", len(completion.seen), "marker occurrences in trajectory:", blob.count("REASONING-MARKER"))
    print("truncations:", sum(e["kind"] == "conversation_truncated" for e in r.trajectory["events"]))
