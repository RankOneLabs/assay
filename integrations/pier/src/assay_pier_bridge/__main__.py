"""Bridge image entrypoint.

Starts immediately against the environment frozen into the image at build
time: it imports the locked dependency set and prints readiness, and never
installs, resolves, or touches a pricing map. Wiring a real ``PierTrialClient``
into ``BridgeRuntime`` is the integration point a Pier deployment supplies;
see README.md for why that client cannot be pinned or vendored here.
"""

from __future__ import annotations

import json
import sys

import assay_pier_bridge


def main() -> int:
    sys.stdout.write(
        json.dumps({"bridge": "assay-pier-bridge", "version": assay_pier_bridge.__version__})
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
