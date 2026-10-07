"""Typed code-metrics failures and partial-analysis policy.

| Condition | Outcome |
| --- | --- |
| Escaping or unsafe snapshot path | SnapshotPathError(ValueError) |
| Malformed or duplicate component configuration | MalformedComponentConfig(ConfigurationError) |
| Reserved `unassigned` component name | ReservedComponentName(ConfigurationError) |
| Overlapping component claims | AmbiguousComponentConfig(ConfigurationError) |
| Component pattern matching zero modules | EmptyComponentPattern(ConfigurationError) |
| Resolved tool version differs from its pin | ToolVersionMismatch(RuntimeError) |
| Node/npx unavailable or jscpd fetch fails | ToolUnavailable(RuntimeError) |
| mypy exits outside 0 or 1 | AnalyzerFailed(RuntimeError) |
| No first-party package | Report: empty graph; propagation_cost and grimp.imports null |
| Python file outside discovered packages | Report: path in coverage.files_without_module |
| Afferent + efferent equals zero | Report: instability null |
| Component has at most one module | Report: internal_dependency_density null |
| Internal edge share has zero denominator | Report: internal_edge_share null |

Null means undefined or unavailable; it never means zero.
"""


class SnapshotPathError(ValueError):
    """A snapshot path is not relative to the repository."""

    operation = "analyze"

    def __init__(self, message: str) -> None:
        super().__init__(f"{self.operation} snapshot path: {message}")


class ConfigurationError(ValueError):
    """Invalid component configuration."""

    operation = "configure components"

    def __init__(self, message: str) -> None:
        super().__init__(f"{self.operation}: {message}")


class MalformedComponentConfig(ConfigurationError):
    """A component name or pattern has an invalid shape."""


class ReservedComponentName(ConfigurationError):
    """A configured component uses the reserved unassigned name."""


class AmbiguousComponentConfig(ConfigurationError):
    """A module was claimed by multiple configured components."""


class EmptyComponentPattern(ConfigurationError):
    """A configured pattern matched no modules."""


class AnalyzerFailed(RuntimeError):
    """An external analyzer could not complete."""

    operation = "run analyzer"

    def __init__(self, message: str) -> None:
        super().__init__(f"{self.operation}: {message}")


class ToolVersionMismatch(RuntimeError):
    """An installed analyzer version disagrees with its declared pin."""

    operation = "resolve tool version"

    def __init__(self, tool: str, expected: str, resolved: str) -> None:
        self.tool = tool
        self.expected = expected
        self.resolved = resolved
        super().__init__(f"resolve tool version {tool}: expected {expected}, resolved {resolved}")


class ToolUnavailable(RuntimeError):
    """A required analyzer cannot be launched or fetched."""

    operation = "run tool"

    def __init__(self, tool: str, reason: str) -> None:
        self.tool = tool
        super().__init__(
            f"run tool {tool}: {reason}; install Node.js and npm (npx), then run npx --yes {tool}"
        )
