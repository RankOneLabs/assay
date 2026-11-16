from pathlib import Path

from code_extension.fact_shapes.alignment import (
    ALLOWLIST,
    check_alignment,
    fact_titles,
    forbidden_tokens,
    lint,
)

ROOT = Path(__file__).resolve().parents[1]


def test_tokens_and_boundaries() -> None:
    for token, source in (
        ("stage/types.ts", "path"),
        ("queued", "key literal"),
        ("acceptValue", "export"),
        ("SessionService", "class"),
    ):
        findings = lint(f"Please change {token}.", {token: (source,)})
        assert len(findings) == 1
        assert (findings[0].token, findings[0].source) == (token, source)
        assert not lint(f"prefix{token}suffix", {token: (source,)})
    assert all(ALLOWLIST.values())
    assert not lint("stage", {"stage": ("key literal",)})


def test_committed_tasks_are_intent_only() -> None:
    forbidden = forbidden_tokens(ROOT / "fact_shapes/holders.json", ROOT / "fact_shapes/base")
    tasks = sorted((ROOT / "fixtures").glob("fact-shapes-*/task.md"))
    assert len(tasks) == 6
    for task in tasks:
        assert not lint(task.read_text(), forbidden), task


def test_alignment_requires_verbatim_sentence() -> None:
    (title,) = fact_titles('test("fact:a: accepts", () => {});')
    table = f"| scenario | {title} | Accept the new value. |"
    assert not check_alignment("scenario", "Accept the new value.", (title,), table)
    assert check_alignment("scenario", "Accept the new value.", (title,), "") == (title,)
    assert check_alignment("scenario", "Other text.", (title,), table) == (title,)


def test_collector_preserves_provenance(tmp_path: Path) -> None:
    holders = tmp_path / "holders.json"
    holders.write_text(
        '[{"manipulated":{"holder_paths":["feature/holder.ts"],'
        '"fact_lines":{"feature/holder.ts":["const registry = { secret_key: true };"]}},'
        '"anchor":{"holder_paths":["feature/anchor.ts"],'
        '"fact_lines":{"feature/anchor.ts":["const anchor = true;"]}}}]'
    )
    base = tmp_path / "base"
    base.mkdir()
    (base / "service.ts").write_text(
        "export class ExampleService {}\nexport function publicEntry() {}\n"
    )
    forbidden = forbidden_tokens(holders, base)
    assert forbidden["feature/holder.ts"] == ("holders.json:path",)
    assert forbidden["holder.ts"] == ("holders.json:basename",)
    assert forbidden["secret_key"] == ("holders.json:identifier",)
    assert forbidden["ExampleService"] == ("base export:service.ts",)
    assert forbidden["publicEntry"] == ("base export:service.ts",)
