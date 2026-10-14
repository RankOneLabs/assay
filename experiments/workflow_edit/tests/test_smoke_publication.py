from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from assay.investigations.workflow_correctness import workflow_tree_digest
from workflow_edit.smoke import SMOKE_CHECKS, _digest, fixture_files, publish, validate_publication


def _evidence() -> dict[str, Any]:
    oakridge = Path('/home/steve/codes/rol/oakridge')
    if not (oakridge / '.git').exists():
        pytest.skip('pinned Oakridge checkout is unavailable')
    snapshot = fixture_files(oakridge)
    manifest = json.loads(
        (Path(__file__).resolve().parents[1] / 'fixtures/smoke/MANIFEST.json').read_text()
    )
    assert workflow_tree_digest(snapshot) == manifest['per_arm_tree_digests']['mess-00']
    image, container_id = manifest['observed_runtime_image_digest'], 'observed-container'
    raw = {
        'Id': container_id, 'State': {'ExitCode': 0},
        'HostConfig': {'NetworkMode': 'none', 'Memory': 1073741824, 'PidsLimit': 64},
        'SizeRw': 2732032, 'Image': image,
        'Mounts': [{'Destination': '/work', 'Type': 'bind', 'Source': '/fixture'}],
    }
    tree = workflow_tree_digest(snapshot)
    artifacts = {
        'trajectory.json': json.dumps({'docker_log': 'offline checks passed\n'}).encode(),
        'candidate.patch': b'',
        'result.json': json.dumps({'exit_code': 0}).encode(),
        'configuration.json': json.dumps({
            'network': 'none', 'image': image, 'container_id': container_id,
        }).encode(),
        'candidate-index.json': json.dumps(sorted(snapshot)).encode(),
        'tree-digest.txt': tree.encode(),
        **{f'candidate_files/{name}': content.encode() for name, content in snapshot.items()},
    }
    sealed = {
        'schema_version': 'assay-pier-artifact-manifest/0.2.0',
        'exchange': {'binding': {'image_digest': image}},
        'entries': [
            {'path': name, 'size_bytes': len(data), 'checksum': _digest(data)}
            for name, data in sorted(artifacts.items())
        ],
        'aggregate_bytes': sum(len(data) for data in artifacts.values()),
    }
    artifacts['manifest.json'] = json.dumps(sealed).encode()
    checks = [
        {'kind': 'harness_check', 'step': step, 'command': command,
         'exit_code': 0, 'output': 'exit=0\n# pass 1\n' if step == 'test' else 'exit=0\n'}
        for step, command in SMOKE_CHECKS
    ]
    records = [
        {
            'cell_id': f'smoke:mess-00:w{index}', 'status': 'complete',
            'requests': 2, 'cost_usd': None,
            'events': [
                *checks,
                *[{'kind': 'model_request', 'turn': turn, 'billing': 'uncertain',
                   'smithers_job_id': f'job-{index}-{turn}', 'prompt_tokens': 10,
                   'completion_tokens': 5, 'queue_latency_seconds': 0.1,
                   'wall_seconds': 1.0} for turn in (1, 2)],
                {'kind': 'cgroup_peaks', 'memory_peak_bytes': 1024, 'pids_peak': 2},
                {'kind': 'submitted', 'turn': 2},
            ],
            'messages': [
                {'role': 'assistant', 'tool_calls': [{'id': f'call-{index}', 'function': {
                    'name': 'read_file', 'arguments': json.dumps({'path': 'package.json'}),
                }}]},
                {'role': 'tool', 'tool_call_id': f'call-{index}', 'content': 'exit=0\n'},
                {'role': 'assistant', 'tool_calls': [{'id': f'submit-{index}', 'function': {
                    'name': 'submit_output', 'arguments': json.dumps({'source': 'done'}),
                }}]},
            ],
        }
        for index in range(20)
    ]
    return {
        'container': {'client': 'docker inspect', 'container_id': container_id, 'raw': raw},
        'binding': {
            'client': 'qualify_local.py + docker inspect', 'container_id': container_id,
            'mount_source': '/fixture',
            'artifact_count': len(artifacts) - 1,
            'manifest_digest': _digest(artifacts['manifest.json']), 'tree_digest': tree,
            'artifacts_base64': {
                name: base64.b64encode(data).decode() for name, data in artifacts.items()
            },
        },
        'model_trial': {
            'client': 'smithers+pier-model-loop',
            'route': {'endpoint': 'http://willie:8900', 'model': 'qwen-coder-32b',
                      'provider': 'smithers-local'},
            'records': records, 'paid_route_reachable': False,
            'admission': {
                'budget_halt': 'budget_exhausted', 'capacity_halt': 'ceiling_exhausted',
                'missing_billing_coverage': 'uncertain', 'missing_billing_amount': None,
            },
            'drop_response': {
                'forced_drop': True, 'first_committed_job_id': 'same-id',
                'redispatch_job_id': 'same-id', 'completions': 1,
                'listed_jobs_with_id': 1,
            },
            'package_snapshot': snapshot,
        },
    }


def test_rejects_host_driver_and_single_request_cell() -> None:
    evidence = _evidence()
    evidence['container']['client'] = 'host_driver'
    with pytest.raises(ValueError, match='docker inspect'):
        validate_publication(evidence)
    evidence = _evidence()
    evidence['model_trial']['records'][0]['requests'] = 1
    with pytest.raises(ValueError, match='multi-model-request'):
        validate_publication(evidence)


def test_accepts_complete_provenance() -> None:
    validate_publication(_evidence())


def test_rejects_text_only_checks_and_unbound_snapshot() -> None:
    evidence = _evidence()
    record = evidence['model_trial']['records'][0]
    record['events'] = [item for item in record['events'] if item['kind'] != 'harness_check']
    with pytest.raises(ValueError, match='harness-controlled'):
        validate_publication(evidence)
    evidence = _evidence()
    evidence['model_trial']['package_snapshot']['package.json'] = 'x'
    with pytest.raises(ValueError, match='pinned tree digest'):
        validate_publication(evidence)


def test_rejects_unbound_artifact_manifest() -> None:
    evidence = _evidence()
    evidence['binding']['manifest_digest'] = 'sha256:' + '0' * 64
    with pytest.raises(ValueError, match='binding manifest digest'):
        validate_publication(evidence)
    evidence = _evidence()
    evidence['binding']['mount_source'] = '/another-fixture'
    with pytest.raises(ValueError, match='binding fixture mount'):
        validate_publication(evidence)


def test_rejects_operator_supplied_measurement_number() -> None:
    evidence = _evidence()
    evidence['model_trial']['measurements'] = {'failure_rate': 0}
    with pytest.raises(ValueError, match='unsupported supplied measurement'):
        validate_publication(evidence)


def test_publication_refuses_host_echo_and_single_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report, evidence_path = tmp_path / 'SMOKE.md', tmp_path / 'evidence.json'
    evidence = _evidence()
    evidence['container']['client'] = 'host_driver'
    evidence_path.write_text(json.dumps(evidence))
    with pytest.raises(ValueError, match='docker inspect'):
        publish(evidence_path, report)
    assert not report.exists()
    evidence = _evidence()
    evidence['model_trial']['records'][0]['requests'] = 1
    evidence_path.write_text(json.dumps(evidence))

    def inspect(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=0,
                                           stdout=json.dumps([evidence['container']['raw']]))

    monkeypatch.setattr('workflow_edit.smoke.subprocess.run', inspect)
    with pytest.raises(ValueError, match='multi-model-request'):
        publish(evidence_path, report)
    assert not report.exists()
