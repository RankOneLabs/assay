"""Resource limits shared by the wire profile and statistical entry points."""

MAX_BOOTSTRAP_SAMPLES = 100_000


def validate_sampling(*, seed: int, samples: int) -> None:
    if (
        type(samples) is not int
        or not 100 <= samples <= MAX_BOOTSTRAP_SAMPLES
        or type(seed) is not int
        or seed < 0
    ):
        raise ValueError(
            f"integer samples in [100, {MAX_BOOTSTRAP_SAMPLES}] and integer seed>=0 required"
        )
