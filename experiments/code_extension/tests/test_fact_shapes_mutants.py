from code_extension.fact_shapes.attempts import Fact, Group, HolderSpec
from code_extension.fact_shapes.cells import FactId, RepositoryPath
from code_extension.fact_shapes.mutants import Run, verdict


def facts() -> tuple[Fact, ...]:
    return tuple(
        Fact(
            FactId(name),
            (f"fact:{name}: accepts",),
            "reference",
            HolderSpec((RepositoryPath("policy.ts"),), ()),
        )
        for name in ("control", "anchor")
    )


def replay(control: str = "fail", anchor: str = "pass", regression: str = "passed") -> Run:
    return Run(
        {
            "visible_regression": Group(status=regression),
            "hidden_regression": Group(status="passed"),
            "new_behavior": Group(
                status="failed" if "fail" in (control, anchor) else "passed",
                stdout=f"({control}) fact:control: accepts\n({anchor}) fact:anchor: accepts\n",
            ),
        }
    )


def test_drop_requires_only_its_own_miss() -> None:
    good = replay()
    assert verdict("reference", "drop-control", facts(), (good, good), FactId("control")).passed
    for bad in (replay(anchor="fail"), replay(regression="failed"), replay(control="pass")):
        result = verdict("reference", "drop-control", facts(), (bad, bad), FactId("control"))
        assert not result.passed
        assert result.arm == "reference" and result.patch == "drop-control" and result.fact


def test_reference_and_reproduction() -> None:
    good = replay(control="pass")
    assert verdict("reference", "reference", facts(), (good, good)).passed
    assert not verdict("reference", "reference", facts(), (good, replay())).passed
    assert not verdict("reference", "reference", facts(), (good,)).passed


def test_holder_only_typecheck() -> None:
    control, anchor = facts()
    control = Fact(control.id, control.titles, "type_enforced", control.holder)
    good = Run({}, "typecheck_failed", "policy.ts(1,1): error TS2322: missing value")
    assert verdict(
        "type_enforced", "drop-control", (control, anchor), (good, good), control.id
    ).passed
    bad = Run(
        {}, "typecheck_failed", good.typecheck_output + "\nother.ts(2,1): error TS2322: broken"
    )
    assert not verdict(
        "type_enforced", "drop-control", (control, anchor), (bad, bad), control.id
    ).passed


def test_missing_titles_do_not_prove_a_miss() -> None:
    good = replay()
    groups = dict(good.groups)
    groups["new_behavior"] = Group(status="failed", stdout="(pass) fact:anchor: accepts")
    missing = Run(groups)
    assert not verdict(
        "reference", "drop-control", facts(), (missing, missing), FactId("control")
    ).passed
