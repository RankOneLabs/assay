"""Typed failures from code metrics."""

class SnapshotPathError(ValueError):
    """A snapshot path is not relative to the repository."""


class AnalyzerFailed(RuntimeError):
    """An external analyzer could not complete."""


class ToolVersionMismatch(RuntimeError):
    """An installed analyzer version disagrees with its declared pin."""

    def __init__(self, tool: str, expected: str, resolved: str) -> None:
        self.tool = tool
        self.expected = expected
        self.resolved = resolved
        super().__init__(f"{tool}: expected {expected}, resolved {resolved}")
