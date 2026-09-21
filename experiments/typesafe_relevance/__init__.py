"""Reference implementation for the Typesafe relevance study."""

from typesafe_relevance.catalogue import Catalogue, load_catalogue
from typesafe_relevance.mappings import decide_argmax
from typesafe_relevance.state import build_state

__all__ = ["Catalogue", "build_state", "decide_argmax", "load_catalogue"]
