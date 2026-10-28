"""TypeScript grammar extraction covers definitions, references, and structure."""

import pytest

from assay.code_intel.typescript_symbols import extract_typescript_symbols
from assay.code_metrics.errors import AnalyzerFailed


def test_typescript_and_tsx_symbols_have_spans_signatures_and_references() -> None:
    result = extract_typescript_symbols({
        "src/a.ts": "export function greet(name: string): string { return name; }\n",
        "src/view.tsx": "export const View = () => <div>Hello</div>;\n",
        "README.md": "no TypeScript here",
    })
    greet = next(item for item in result.definitions if item.name == "greet")
    assert (greet.file_path, greet.start_line, greet.end_line) == ("src/a.ts", 1, 1)
    assert greet.signature == "function greet(name: string): string"
    assert any(ref.name == "name" and ref.file_path == "src/a.ts" for ref in result.references)
    assert any(item.kind == "function_declaration" for item in result.structures)
    assert any(item.name == "View" and item.file_path == "src/view.tsx"
               for item in result.definitions)
    assert result.coverage.files_analyzed == 2
    assert result.coverage.files_without_module == ("README.md",)


def test_parser_failure_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_: bytes) -> None:
        raise RuntimeError("parser unavailable")

    class BrokenParser:
        def __init__(self, language: object) -> None:
            pass

        parse = staticmethod(fail)

    monkeypatch.setattr("assay.code_intel.typescript_symbols.Parser", BrokenParser)
    with pytest.raises(AnalyzerFailed, match="parse src/a.ts: parser unavailable"):
        extract_typescript_symbols({"src/a.ts": "export const a = 1;"})
