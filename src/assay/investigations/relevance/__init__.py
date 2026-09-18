"""Reference implementation for the Typesafe relevance study."""

from assay.investigations.relevance.catalogue import Catalogue, load_catalogue
from assay.investigations.relevance.mappings import decide_argmax
from assay.investigations.relevance.state import build_state

__all__ = ["Catalogue", "build_state", "decide_argmax", "load_catalogue"]
