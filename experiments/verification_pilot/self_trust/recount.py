"""Recompute every number on the published study page from the attempt-level ledger.

This reads only a ledger CSV and the committed PR-size data. Its calculations
are independent of the study measures; it shares only the protocol's exclusion
predicate and the Wilson helper. Each claim
names its page location, the published value, the archives it draws on and
the calculation. Two counting rules are applied:

- **study rule** (the page's stated exclusions): drop a session stopped by the
  spend cap, an unbilled provider error (``provider_*``, ``billing_uncertain``)
  or a transport failure. Everything else counts, and a missed session's
  verdict is its last submitted T2/T3 verdict, else "limit" if a limit or
  deadline stopped it, else "no verdict".
- **audit rule**: the study rule, plus drop a session whose last model request
  ended with ``finish_reason`` "error" (the ledger's ``provider_error`` status
  on a ``no_tool_call`` stop), since that is an unbilled provider error the
  harness recorded as a prose ending.

For each claim the output also gives planned, ran, excluded, completed-valid
and restored counts, so infrastructure losses are visible, and a 95% Wilson
interval on the study-rule rate.

Run ``uv run python -m verification_pilot.self_trust.recount`` from ``experiments/``.
Writes CSVs under ``/tmp/self-trust-report`` by default.
"""

from __future__ import annotations

import csv
import json
import math
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from verification_pilot.self_trust.settings import excluded_cause
from verification_pilot.self_trust.wilson import wilson

AUDIT = Path("/tmp/self-trust-report")
LEDGER = AUDIT / "ledger.csv"
PR_SIZES = Path(__file__).resolve().parents[1] / "raw" / "self_trust" / "oakridge-pr-sizes.json"
LOCAL_ROUTE = "qwen3.6-27b"

Row = dict[str, str]


def study_excluded(row: Row) -> bool:
    return excluded_cause(row["terminal_cause"])


def audit_excluded(row: Row) -> bool:
    return study_excluded(row) or row["terminal_status"] == "provider_error"


def fixed(row: Row) -> bool:
    return row["remnant_fixed"] == "True"


def miss_verdict(row: Row) -> str:
    if row["last_verdict"]:
        return row["last_verdict"]
    if row["terminal_status"] in ("agent_limit", "timeout"):
        return "limit"
    return "no verdict"


@dataclass
class Claim:
    claim_id: str
    location: str
    published: str
    runs: tuple[str, ...]
    calculation: str
    measure: Callable[[list[Row]], str]
    select: Callable[[Row], bool] = field(default=lambda row: True)


def restored(rows: list[Row]) -> str:
    return f"{sum(fixed(r) for r in rows)} of {len(rows)}"


def restored_with_verdicts(rows: list[Row]) -> str:
    verdicts = Counter(miss_verdict(r) for r in rows if not fixed(r))
    return f"{restored(rows)}; misses: " + ", ".join(
        f"{n} {v}" for v, n in sorted(verdicts.items())
    )


def by_framing(rows: list[Row]) -> str:
    own = [r for r in rows if r["framing"] == "own"]
    mate = [r for r in rows if r["framing"] == "teammate"]
    return f"{restored(rows)}; own {restored(own)}; teammate {restored(mate)}"


def complete_misses(rows: list[Row]) -> str:
    misses = [r for r in rows if not fixed(r)]
    return (
        f"{sum(miss_verdict(r) == 'complete' for r in misses)} of {len(misses)} misses 'complete'"
    )


def read_any_turn(row: Row) -> bool:
    return "True" in (row["module_read_t1"], row["module_read_t2"], row["module_read_t3"])


def opened(rows: list[Row]) -> str:
    read = [r for r in rows if read_any_turn(r)]
    restores = sum(fixed(r) for r in rows)
    return (
        f"opened in {len(read)} of {len(rows)}; "
        f"restores among them {sum(fixed(r) for r in read)} of {restores}"
    )


def opened_t1(rows: list[Row]) -> str:
    return (
        f"opened in T1 in {sum(r['module_read_t1'] == 'True' for r in rows)} of {len(rows)}; "
        f"any turn {sum(read_any_turn(r) for r in rows)}"
    )


def max_requests(rows: list[Row]) -> str:
    return f"max {max(int(r['requests']) for r in rows)} requests"


def per_omission(rows: list[Row]) -> str:
    parts = []
    for omission in ("remnant_a", "remnant_b", "remnant_c"):
        sub = [r for r in rows if r["omission"] == omission]
        own = [r for r in sub if r["framing"] == "own"]
        mate = [r for r in sub if r["framing"] == "teammate"]
        parts.append(f"{omission}: own {restored(own)}, teammate {restored(mate)}")
    return "; ".join(parts)


def model(name: str) -> Callable[[Row], bool]:
    return lambda row: row["model"].split("/")[-1] == name


L3_MODELS = {
    "gpt-6.1-sol": ("7 of 12; own 4 of 7; teammate 3 of 5", "4 unsure, 1 incomplete"),
    "claude-sonnet-5.5": ("1 of 8; own 1 of 3; teammate 0 of 5", "3 incomplete, 4 no verdict"),
    "gemini-4-argon": ("0 of 6; own 0 of 3; teammate 0 of 3", "4 complete, 2 no verdict"),
    "ministral-14b-2512": ("0 of 6; own 0 of 3; teammate 0 of 3", "6 complete"),
    "deepseek-v4-pro": ("0 of 5; own 0 of 2; teammate 0 of 3", "3 complete, 1 no verdict, 1 limit"),
    "gemini-3.8-flash": ("0 of 8; own 0 of 4; teammate 0 of 4", "3 complete, 5 limit"),
    "kimi-k2.7-code": ("0 of 6; own 0 of 3; teammate 0 of 3", "2 complete, 4 limit"),
    "gpt-6-luna": ("0 of 6; own 0 of 3; teammate 0 of 3", "1 complete, 5 incomplete"),
    "claude-haiku-5.5": (
        "0 of 6; own 0 of 3; teammate 0 of 3",
        "1 incomplete, 4 no verdict, 1 limit",
    ),
    "gpt-oss-20b": ("0 of 6; own 0 of 3; teammate 0 of 3", "6 no verdict"),
    "qwen3.8-2.4t-a95b": ("0 of 4; own 0 of 2; teammate 0 of 2", "4 limit"),
    "qwen3.8-27b": ("0 of 2; own 0 of 1; teammate 0 of 1", "2 limit"),
}
L3_RUNS = (
    "13719646",
    "1c8be64b",
    "217d63c3",
    "22db85bc",
    "2b21347e",
    "36d62df0",
    "39603b39",
    "3cb59616",
    "40f328ef",
    "414b5927",
    "4db6069a",
    "56e4e366",
    "59bb7fbd",
    "72c5ca9c",
    "772e5410",
    "78660eae",
    "84932da0",
    "8b9e9666",
    "9e24b30e",
    "a2310fc3",
    "ac955a91",
    "cdb19371",
    "d05ad588",
    "d434fb0b",
    "dd67e400",
    "df5b61b8",
    "ee3042b2",
)
MOVE_ARGON = ("90b75097", "dc8939df")
REWRITE0 = ("b70afd75", "52ca8956", "4402110b")
REWRITE0_READ = ("839e4c5c", "ff6dd246")
REWRITE1 = ("82d125fb", "e8345348", "64fcf385", "023dc4f8")
ARGON_REWRITES = REWRITE0 + REWRITE0_READ + REWRITE1 + ("c728d1cb", "ac955a91")

CLAIMS = [
    Claim(
        "H1",
        "README headline table, row 1",
        "36 of 36",
        MOVE_ARGON + ("df496bc1", "7fe13e8f", "aed117c0"),
        "restored / kept",
        restored,
    ),
    Claim(
        "H2",
        "README headline table, row 2",
        "2 of 17",
        REWRITE0 + ("472c12bd", "99a4fd07"),
        "restored / kept",
        restored,
    ),
    Claim(
        "H3",
        "README headline table, row 3",
        "11 of 11",
        ("bfd8a263", "5976c4f9"),
        "restored / kept",
        restored,
    ),
    Claim(
        "H4",
        "README headline table, row 4",
        "0 of 12, with 10 signed off as complete",
        ("ffe47efa", "eb94295c"),
        "restored / kept; last verdict on misses",
        restored_with_verdicts,
    ),
    Claim(
        "H5",
        "README headline table, row 5",
        "8 of 75 (12 models; 10 restored none)",
        L3_RUNS,
        "restored / kept, local Qwen3.6 route excluded",
        restored,
    ),
    Claim(
        "F1-move",
        "Finding 1 table, 436-line move",
        "18 of 18",
        MOVE_ARGON,
        "restored / kept",
        restored,
    ),
    Claim(
        "F1-move-long",
        "Finding 1 table, move with file reads",
        "6 of 6",
        ("df496bc1",),
        "restored / kept",
        restored,
    ),
    Claim(
        "F1-r0",
        "Finding 1 table, 693-line rewrite",
        "0 of 10",
        REWRITE0,
        "restored / kept",
        restored,
    ),
    Claim(
        "F1-r0read",
        "Finding 1 table, 693-line rewrite with old modules read",
        "0 of 10",
        REWRITE0_READ,
        "restored / kept",
        restored,
    ),
    Claim(
        "F1-L1",
        "Finding 1 table, 1,097-line rewrite",
        "0 of 10",
        REWRITE1,
        "restored / kept",
        restored,
    ),
    Claim(
        "F1-L2",
        "Finding 1 table, 2,137-line rewrite",
        "1 of 5",
        ("c728d1cb",),
        "restored / kept",
        restored,
    ),
    Claim(
        "F1-L3",
        "Finding 1 table, 2,782-line rewrite",
        "0 of 6",
        ("ac955a91",),
        "restored / kept",
        restored,
    ),
    Claim(
        "F1-41",
        "Finding 1 text, opened the omission's file",
        "4 of 41 rewrite sessions; the one restore among them",
        ARGON_REWRITES,
        "module_read in any turn",
        opened,
    ),
    Claim(
        "F1-argon-verdicts",
        "Finding 1 breadth table, Argon rewrite misses",
        "0 of 10; 3 complete, 7 incomplete",
        REWRITE0,
        "last verdict on misses",
        restored_with_verdicts,
    ),
    Claim(
        "F1-sonnet-move",
        "Finding 1 breadth table, Sonnet move",
        "6 of 6",
        ("7fe13e8f",),
        "restored / kept",
        restored,
    ),
    Claim(
        "F1-sonnet-r0",
        "Finding 1 breadth table, Sonnet rewrite",
        "2 of 4; 1 incomplete, 1 no verdict",
        ("472c12bd",),
        "restored / kept; last verdict on misses",
        restored_with_verdicts,
    ),
    Claim(
        "F1-flash-move",
        "Finding 1 breadth table, Flash move",
        "6 of 6",
        ("aed117c0",),
        "restored / kept",
        restored,
    ),
    Claim(
        "F1-flash-r0",
        "Finding 1 breadth table, Flash rewrite",
        "0 of 3; 3 complete",
        ("99a4fd07",),
        "restored / kept; last verdict on misses",
        restored_with_verdicts,
    ),
    Claim(
        "F1-flash-open-move",
        "Finding 1 text, Flash opened the file in T1, move",
        "all 6",
        ("aed117c0",),
        "module_read T1",
        opened_t1,
    ),
    Claim(
        "F1-flash-open-r0",
        "Finding 1 text, Flash opened the file, rewrite",
        "1 of 3, only in its last turn",
        ("99a4fd07",),
        "module_read per turn",
        opened_t1,
    ),
    Claim(
        "F2-forge-move-argon",
        "Finding 2 table",
        "6 of 6",
        ("80206567",),
        "restored / kept",
        restored,
    ),
    Claim(
        "F2-forge-move-flash",
        "Finding 2 table",
        "no result",
        ("b9814d1a", "121df55a"),
        "restored / kept",
        restored,
    ),
    Claim(
        "F2-forge-rewrite-argon",
        "Finding 2 table",
        "6 of 6",
        ("bfd8a263",),
        "restored / kept",
        restored,
    ),
    Claim(
        "F2-forge-rewrite-flash",
        "Finding 2 table",
        "5 of 5",
        ("5976c4f9",),
        "restored / kept",
        restored,
    ),
    Claim(
        "F2-146-argon",
        "Finding 2 table",
        "0 of 6, 5 complete",
        ("ffe47efa",),
        "restored / kept; last verdict on misses",
        restored_with_verdicts,
    ),
    Claim(
        "F2-146-flash",
        "Finding 2 table",
        "0 of 6, 5 complete",
        ("eb94295c",),
        "restored / kept; last verdict on misses",
        restored_with_verdicts,
    ),
    *[
        Claim(
            f"F3-{name}",
            "Finding 3 table",
            f"{counts}; misses: {verdicts}",
            L3_RUNS,
            "restored / kept by framing; last verdict on misses",
            lambda rows: (
                by_framing(rows)
                + "; misses: "
                + restored_with_verdicts(rows).split("; misses: ")[1]
            ),
            model(name),
        )
        for name, (counts, verdicts) in L3_MODELS.items()
    ],
    Claim(
        "F3-complete",
        "Finding 3 text",
        "19 of 67 misses 'complete'",
        L3_RUNS,
        "misses whose last verdict is complete",
        complete_misses,
    ),
    Claim(
        "F3-kimi-requests",
        "Finding 3 text, loose limits",
        "up to 107 requests",
        ("40f328ef",),
        "max requests in a session",
        max_requests,
        model("kimi-k2.7-code"),
    ),
    Claim(
        "SELF-sol",
        "What we could not answer, Sol table",
        "remnant_a: own 3 of 5, teammate 2 of 2; remnant_b: own 1 of 1, teammate 1 of 1; "
        "remnant_c: own 0 of 1, teammate 0 of 2",
        L3_RUNS,
        "restored / kept per omission and framing",
        per_omission,
        model("gpt-6.1-sol"),
    ),
    Claim(
        "H5-without-C",
        "Sensitivity, not on the page (REPORT A13)",
        "not published",
        L3_RUNS,
        "restored / kept, omissions A and B only",
        restored,
        lambda row: row["omission"] != "remnant_c",
    ),
    Claim(
        "H5-C-only",
        "Sensitivity, not on the page (REPORT A13)",
        "not published",
        L3_RUNS,
        "restored / kept, omission C only",
        restored,
        lambda row: row["omission"] == "remnant_c",
    ),
    Claim(
        "SELF-quoted",
        "What we could not answer, attribution variants",
        "12 of 12 quoted",
        ("dc8939df",),
        "restored / kept, quoted arms",
        restored,
        lambda row: row["arm_id"].startswith("st-quoted"),
    ),
    Claim(
        "SELF-turns",
        "What we could not answer, own log as own turns",
        "6 of 6",
        ("90b75097",),
        "restored / kept, native arm",
        restored,
    ),
]


def evaluate(claim: Claim, rows: list[Row]) -> tuple[dict[str, str], list[Row]]:
    chosen = [
        r
        for r in rows
        if r["run_id"][:8] in claim.runs and r["model"] != LOCAL_ROUTE and claim.select(r)
    ]
    ran = [r for r in chosen if r["terminal_status"] != "not_run"]
    study = [r for r in ran if not study_excluded(r)]
    audit = [r for r in ran if not audit_excluded(r)]
    valid = [r for r in ran if r["terminal_status"] == "completed_valid"]
    recomputed = claim.measure(study) if study else "no kept sessions"
    return {
        "claim_id": claim.claim_id,
        "location": claim.location,
        "published": claim.published,
        "recomputed_study_rule": recomputed,
        "recomputed_audit_rule": claim.measure(audit) if audit else "no kept sessions",
        "calculation": claim.calculation,
        "runs": " ".join(claim.runs),
        "planned": str(len(chosen)),
        "ran": str(len(ran)),
        "excluded_study_rule": str(len(ran) - len(study)),
        "completed_valid": str(len(valid)),
        "restored": str(sum(fixed(r) for r in study)),
        "restored_completed_valid": f"{sum(fixed(r) for r in valid)} of {len(valid)}",
        "restored_all_planned": f"{sum(fixed(r) for r in study)} of {len(chosen)}",
        "wilson95_study_rule": wilson(sum(fixed(r) for r in study), len(study)),
        "statuses": json.dumps(Counter(r["terminal_status"] for r in chosen), sort_keys=True),
    }, chosen


def pr_size_claims() -> list[dict[str, str]]:
    data = json.loads(PR_SIZES.read_text(encoding="utf-8"))
    cohort = sorted(r["code_lines"] for r in data["rows"] if r["cohort"])
    summary = data["summary"]["cohort"]
    pr605: dict[str, object] = next((r for r in data["rows"] if r["number"] == 605), {})

    def below(lines: int) -> str:
        return f"{round(100 * sum(c < lines for c in cohort) / len(cohort))}%"

    rows = [
        (
            "PR-cohort",
            "README sizing paragraph",
            "212 merged PRs, median 660, 90th percentile 2,406",
            f"{len(cohort)} PRs, median {summary['code_median']}, p90 {summary['code_p90']}",
        ),
        (
            "PR-605",
            "README sizing paragraph",
            "672 lines of code and 47,402 of everything else",
            f"{pr605.get('code_lines')} code, {pr605.get('other_lines')} other",
        ),
    ]
    for lines, published in (
        (436, "36%"),
        (693, "55%"),
        (1097, "72%"),
        (2137, "86%"),
        (2782, "91%"),
    ):
        rows.append(
            (
                f"PR-{lines}",
                "README refactor table",
                published,
                f"{below(lines)} of cohort PRs below {lines}",
            )
        )
    return [
        {
            "claim_id": c,
            "location": loc,
            "published": pub,
            "recomputed_study_rule": got,
            "recomputed_audit_rule": got,
            "calculation": "share of cohort PRs with fewer code lines",
            "runs": "raw/self_trust/oakridge-pr-sizes.json",
        }
        for c, loc, pub, got in rows
    ]


def fisher_two_sided(a: int, b: int, c: int, d: int) -> float:
    """Exact two-sided p for the 2x2 table [[a, b], [c, d]]."""

    def p(x: int) -> float:
        return math.comb(a + b, x) * math.comb(c + d, a + c - x) / math.comb(a + b + c + d, a + c)

    observed = p(a)
    low, high = max(0, a + c - (c + d)), min(a + b, a + c)
    return min(1.0, sum(p(x) for x in range(low, high + 1) if p(x) <= observed * (1 + 1e-9)))


def framing_rows(rows: list[Row]) -> list[dict[str, str]]:
    """Own versus teammate restore rates per fixture and model, study rule, with an exact test."""
    kept = [
        r
        for r in rows
        if r["terminal_status"] != "not_run"
        and not study_excluded(r)
        and r["model"] != LOCAL_ROUTE
        and r["framing"] in ("own", "teammate")
        and r["fixture"] != "stage_run"
        and r["run_id"][:8] != "68ef25b0"
    ]
    groups: dict[tuple[str, str], list[Row]] = {}
    for r in kept:
        groups.setdefault((r["fixture"], r["model"].split("/")[-1]), []).append(r)
    groups[("all", "all")] = kept
    out = []
    for (fixture, name), sub in sorted(groups.items()):
        own = [r for r in sub if r["framing"] == "own"]
        mate = [r for r in sub if r["framing"] == "teammate"]
        a, c = sum(fixed(r) for r in own), sum(fixed(r) for r in mate)
        out.append(
            {
                "fixture": fixture,
                "model": name,
                "own": f"{a} of {len(own)}",
                "teammate": f"{c} of {len(mate)}",
                "fisher_p": f"{fisher_two_sided(a, len(own) - a, c, len(mate) - c):.3f}",
            }
        )
    return out


def main() -> None:
    (AUDIT / "ledger").mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(LEDGER.open(encoding="utf-8")))
    framing = framing_rows(rows)
    with (AUDIT / "ledger" / "framing.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(framing[0]))
        writer.writeheader()
        writer.writerows(framing)
    out_claims, out_rows = [], []
    for claim in CLAIMS:
        result, chosen = evaluate(claim, rows)
        out_claims.append(result)
        out_rows += [
            {
                "claim_id": claim.claim_id,
                "run_id": r["run_id"],
                "cell_id": r["cell_id"],
                "terminal_status": r["terminal_status"],
                "counted_study_rule": str(
                    r["terminal_status"] != "not_run" and not study_excluded(r)
                ),
                "remnant_fixed": r["remnant_fixed"],
                "trajectory_ref": r.get("trajectory_ref", ""),
            }
            for r in chosen
        ]
    out_claims += pr_size_claims()
    fields = list(out_claims[0])
    with (AUDIT / "ledger" / "claims.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(out_claims)
    with (AUDIT / "ledger" / "claim-rows.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(out_rows[0]))
        writer.writeheader()
        writer.writerows(out_rows)
    for c in out_claims:
        pad = " " * 24
        print(f"{c['claim_id']:24} published: {c['published']}")
        print(f"{pad} study rule: {c['recomputed_study_rule']}")
        print(f"{pad} audit rule: {c['recomputed_audit_rule']}")


if __name__ == "__main__":
    main()
