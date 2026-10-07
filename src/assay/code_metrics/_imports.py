"""Synchronization for Grimp's process-global import path."""

from threading import Lock

IMPORT_LOCK = Lock()
