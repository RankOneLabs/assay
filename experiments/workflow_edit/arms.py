"""Fixed arm identifiers for the workflow edit experiment."""

from pydantic import TypeAdapter

from assay.models import Identifier

_identifier = TypeAdapter(Identifier)

MESS_00: str = _identifier.validate_python("mess-00")
MESS_LOW: str = _identifier.validate_python("mess-low")
MESS_MID: str = _identifier.validate_python("mess-mid")
MESS_HIGH: str = _identifier.validate_python("mess-high")

ARM_IDS: tuple[str, str, str, str] = (MESS_00, MESS_LOW, MESS_MID, MESS_HIGH)
