"""Code extension study model and pre-dispatch validation."""

import sys
from pathlib import Path

# The bridge is a separate source project, shared with the earlier studies.
_BRIDGE_SRC = Path(__file__).resolve().parents[2] / "integrations" / "pier" / "src"
if str(_BRIDGE_SRC) not in sys.path:
    sys.path.insert(0, str(_BRIDGE_SRC))
