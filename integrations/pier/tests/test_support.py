"""Synthetic authorized exchange for isolated bridge tests."""

from assay_pier_bridge.protocol import CellCoordinate, PierExchange, RuntimeBinding


def exchange_for(cell_id: str, package_digest: str) -> PierExchange:
    subject_id, arm_id, repeat = cell_id.split(":")
    coordinate = CellCoordinate(
        subject_id=subject_id,
        arm_id=arm_id,
        worker_repeat=int(repeat[1:]),
        realization_ref="sha256:" + "0" * 64,
    )
    return PierExchange(
        coordinate=coordinate,
        binding=RuntimeBinding(
            runtime_version="test-lock",
            image_digest="sha256:" + "1" * 64,
            configuration_ref="sha256:" + "2" * 64,
            package_digest=package_digest,
        ),
        trial_name=f"{subject_id.replace('-', '--')}-{arm_id.replace('-', '--')}-{repeat}",
    )
