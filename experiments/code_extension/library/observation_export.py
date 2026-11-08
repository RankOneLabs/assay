"""Two export tasks in oakridge's observation app, at `1495ec34`.

- `restricted-evidence`: give the `restricted` field sensitivity its own evidence kind and
  export allowance, modelled on `repository_content` at every layer it passes through.
- `export-credential`: the local control; a separate export credential.

Both cut the same source: the import closure of `createApp`, which reaches the export route,
grade-context intake, the redaction step and the producer classification. Source moves from
`observation/src/` to `src/` (same depth, so its relative imports are unchanged), selected
tests from `observation/tests/` to `tests/visible/`, and the workspace package
`canonical-json` keeps its own path and is imported by relative path.
"""
# ruff: noqa: E501 - embedded TypeScript keeps the fixture's own line lengths.

from __future__ import annotations

from code_extension.library import HIDDEN_MOVE, RELOCATION, Edit, LibraryTask, Patches, Requirements
from code_extension.slice import Replacement, SliceSpec

_OBS = "observation/"
_SOURCES = (
    "domain/errors.ts", "domain/identity.ts", "domain/primitives.ts",
    "export/jsonl.ts", "export/manifest.ts", "export/redaction.ts",
    "grading/catalogue/oakridge-questions.ts", "grading/coverage.ts", "grading/eligibility.ts",
    "grading/evaluator.ts", "grading/evidence-packages/capture.ts",
    "grading/evidence-packages/judge-recipe.ts", "grading/evidence-packages/pilot-recipe.ts",
    "grading/evidence-packages/recipe.ts", "grading/evidence-packages/references.ts",
    "grading/evidence.ts", "grading/execution.ts", "grading/jobs/budget.ts",
    "grading/observation.ts", "grading/question.ts", "grading/runner.ts",
    "http/app.ts", "http/errors.ts", "http/evaluations.ts", "http/exports.ts", "http/grades.ts",
    "http/grading-records.ts", "http/ingest-auth.ts", "http/items.ts", "http/sources.ts",
    "ingest/capture.ts", "ingest/cursor.ts",
    "ports/artifact-source.ts", "ports/grade-runner.ts",
    "producers/oakridge/classification.ts", "producers/oakridge/eligibility.ts",
    "producers/oakridge/evidence-packages.ts",
    "projection/catalogue/oakridge-development.ts", "projection/extractor.ts",
    "projection/issues.ts", "projection/occurrence-id.ts", "projection/relations.ts",
    "purge/purge.ts", "purge/trigger.ts",
    "runners/coverage-checker.ts", "runners/deterministic-checker.ts", "runners/fastino-glide.ts",
    "runners/human-intake.ts", "runners/jev-direct.ts", "runners/llm-judge.ts",
    "runners/stub-model.ts",
    "storage/backfill-store.ts", "storage/blind-assignment-store.ts",
    "storage/capture-artifact-source.ts", "storage/captured-evidence-store.ts",
    "storage/capture-store.ts", "storage/coverage-store.ts", "storage/database.ts",
    "storage/db-types.ts", "storage/eligibility-store.ts", "storage/export-store.ts",
    "storage/grading-job-store.ts", "storage/grading-record-store.ts", "storage/grading-store.ts",
    "storage/migrate.ts", "storage/projection-store.ts", "storage/run-capture-store.ts",
)
# Every source file that imports the workspace package, which now sits beside src/.
_CANONICAL_IMPORTERS = (
    "export/manifest.ts", "grading/evaluator.ts", "grading/evidence-packages/references.ts",
    "grading/evidence.ts", "grading/execution.ts", "ingest/capture.ts",
    "producers/oakridge/evidence-packages.ts", "projection/issues.ts",
    "projection/occurrence-id.ts", "projection/relations.ts", "runners/deterministic-checker.ts",
    "storage/backfill-store.ts", "storage/capture-artifact-source.ts", "storage/export-store.ts",
    "storage/grading-store.ts", "storage/projection-store.ts",
)
_HIDDEN = "hidden/regression/tests/hidden/regression/"


def _canonical(path: str) -> Replacement:
    up = "../" * path.count("/")
    return Replacement(path, 'from "canonical-json"', f'from "{up}canonical-json/src/index"')


_SOURCE_FILES = {
    **{f"{_OBS}src/{path}": f"src/{path}" for path in _SOURCES},
    "canonical-json/src/index.ts": "canonical-json/src/index.ts",
}
_SOURCE_REPLACEMENTS = (
    *(_canonical(f"src/{path}") for path in _CANONICAL_IMPORTERS),
    # Two template-literal key separators are raw NUL bytes at the pin, and the bridge refuses
    # a working copy holding any NUL. The `\u0000` escape is the same string.
    Replacement("src/producers/oakridge/evidence-packages.ts", "\x00", "\\u0000", 2),
)
_NUL_ESCAPE = (
    "Two raw NUL bytes in template literals in producers/oakridge/evidence-packages.ts are "
    "written as the `\\u0000` escape, which is the same string, because the bridge refuses a "
    "working copy holding NUL bytes."
)
_TYPECHECK = ("src/**/*.ts", "tests/**/*.ts", "canonical-json/**/*.ts")


# --- restricted-evidence ---------------------------------------------------------------

_CLASSIFICATION_HIDDEN = f"{_HIDDEN}classification.test.ts"
_REVERSED_ROW = '  ["brief", "/files_in_scope/0", "internal"],\n'
_REVERSED_TEST = '''
test("a field declared repository content maps to repository content, not internal", () => {
  // No development field is classified repository_content today; the mapping must still
  // carry that kind through rather than failing it closed with restricted content.
  expect(classifyProjectionField("brief", "files_in_scope")).toEqual({ ok: true, value: "restricted" });
  expect(evidenceKindForCapturedPath("brief", "/files_in_scope/0")).toEqual({ ok: true, value: "internal" });
});
'''
_REVERSED_NOTE = '''
// The pinned assertions that brief.files_in_scope evidence is internal are reversed by the
// task; their new expectation is checked in the hidden new-behavior group.
'''

RESTRICTED_EVIDENCE = SliceSpec(
    package_name="oakridge-observation-restricted-evidence",
    files={
        **_SOURCE_FILES,
        f"{_OBS}tests/export-redaction.test.ts": "tests/visible/export-redaction.test.ts",
        f"{_OBS}tests/classification.test.ts": _CLASSIFICATION_HIDDEN,
    },
    replacements=(
        *_SOURCE_REPLACEMENTS,
        Replacement("tests/visible/export-redaction.test.ts", '"../src/', '"../../src/', 4),
        Replacement(_CLASSIFICATION_HIDDEN, '"../src/', '"../../../src/'),
        Replacement(_CLASSIFICATION_HIDDEN, _REVERSED_ROW, ""),
        Replacement(_CLASSIFICATION_HIDDEN, _REVERSED_TEST, _REVERSED_NOTE),
    ),
    typecheck_include=_TYPECHECK,
)

_KIND_TYPE: Edit = (
    "src/grading/evidence.ts",
    'export type EvidenceKind = "raw_build_output" | "raw_test_output" | "repository_content" | "public" | "internal";',
    'export type EvidenceKind = "raw_build_output" | "raw_test_output" | "repository_content" | "restricted" | "public" | "internal";',
)
_KIND_LIST: Edit = (
    "src/grading/evidence-packages/references.ts",
    '["raw_build_output", "raw_test_output", "repository_content", "public", "internal"] as readonly unknown[]',
    '["raw_build_output", "raw_test_output", "repository_content", "restricted", "public", "internal"] as readonly unknown[]',
)
_CLASSIFY: Edit = (
    "src/producers/oakridge/classification.ts",
    '    : classified.value === "repository_content" ? "repository_content" : "internal");',
    '    : classified.value === "repository_content" ? "repository_content"\n'
    '      : classified.value === "restricted" ? "restricted" : "internal");',
)
_INTAKE: Edit = (
    "src/http/evaluations.ts",
    'kind: z.enum(["raw_build_output", "raw_test_output", "repository_content", "public", "internal"]),',
    'kind: z.enum(["raw_build_output", "raw_test_output", "repository_content", "restricted", "public", "internal"]),',
)
_REASON_TYPE: Edit = (
    "src/export/manifest.ts",
    'readonly reason: "raw_build_output" | "raw_test_output" | "repository_content" | "unclassified_content" }',
    'readonly reason: "raw_build_output" | "raw_test_output" | "repository_content" | "restricted_content" | "unclassified_content" }',
)
_POLICY_TYPE: Edit = (
    "src/export/manifest.ts",
    "  readonly allow_repository_content: boolean;\n}",
    "  readonly allow_repository_content: boolean;\n"
    "  /** Restricted evidence content; absent means withheld. */\n"
    "  readonly allow_restricted_content?: boolean;\n}",
)
_REDACT_REASON: Edit = (
    "src/export/redaction.ts",
    '      ? kind : kind === "public" ? null : "unclassified_content";',
    '      ? kind : kind === "restricted" ? "restricted_content" : kind === "public" ? null : "unclassified_content";',
)
_REDACT_ALLOW: Edit = (
    "src/export/redaction.ts",
    '          : reason === "repository_content" ? policy.allow_repository_content : reason === null;',
    '          : reason === "repository_content" ? policy.allow_repository_content\n'
    '            : reason === "restricted_content" ? policy.allow_restricted_content === true : reason === null;',
)
_EXPORT_SCHEMA_OLD = '''    allow_repository_content: z.boolean().default(false),
  }).default({ allow_raw_build_output: false, allow_raw_test_output: false, allow_repository_content: false })
  }).default({ name: "assay", redaction_policy: {
    allow_raw_build_output: false, allow_raw_test_output: false, allow_repository_content: false,
  } }),'''
_EXPORT_SCHEMA: Edit = (
    "src/http/exports.ts",
    _EXPORT_SCHEMA_OLD,
    '''    allow_repository_content: z.boolean().default(false), allow_restricted_content: z.boolean().default(false),
  }).default({ allow_raw_build_output: false, allow_raw_test_output: false, allow_repository_content: false,
    allow_restricted_content: false })
  }).default({ name: "assay", redaction_policy: {
    allow_raw_build_output: false, allow_raw_test_output: false, allow_repository_content: false,
    allow_restricted_content: false,
  } }),''',
)
_EXPORT_GATE: Edit = (
    "src/http/exports.ts",
    "allowances.allow_raw_test_output || allowances.allow_repository_content)",
    "allowances.allow_raw_test_output || allowances.allow_repository_content\n"
    "      || allowances.allow_restricted_content)",
)
_RESTRICTED_EXPORT = (_REASON_TYPE, _POLICY_TYPE, _REDACT_REASON, _REDACT_ALLOW, _EXPORT_SCHEMA)

_RESTRICTED_PATCHES: Patches = {
    "reference.patch": (
        "Add the restricted kind at every layer, its redaction reason and its raw-gated allowance.",
        (_KIND_TYPE, _KIND_LIST, _CLASSIFY, _INTAKE, *_RESTRICTED_EXPORT, _EXPORT_GATE),
    ),
    "unreachable-classification.patch": (
        "Kind, intake, redaction and gate all handle restricted, but classification still maps restricted fields to internal, so captured evidence never carries the kind.",
        (_KIND_TYPE, _KIND_LIST, _INTAKE, *_RESTRICTED_EXPORT, _EXPORT_GATE),
    ),
    "ungated-allowance.patch": (
        "The allowance exists and works, but the export route does not require the raw export credential for it, so a read token exports restricted content.",
        (_KIND_TYPE, _KIND_LIST, _CLASSIFY, _INTAKE, *_RESTRICTED_EXPORT),
    ),
}

_RESTRICTED_REQUIREMENTS: Requirements = (
    ("A body field declared restricted (brief.files_in_scope, assessment.test_evidence) yields "
     "captured evidence of kind restricted, which evidence packaging accepts.",
     ("restricted-classifies", "restricted-packages")),
    ("Grade-context intake accepts evidence references of kind restricted, and their content "
     "reaches export with that kind.",
     ("intake-withholds-restricted", "intake-releases-restricted")),
    ("Export withholds restricted evidence content with redaction reason restricted_content "
     "unless the redaction policy sets allow_restricted_content; an absent flag means false, and "
     "no other allowance releases it.",
     ("restricted-withheld-by-default", "repository-allowance-keeps-restricted",
      "restricted-allowance-only-restricted")),
    ("Requesting allow_restricted_content on POST /v1/exports/assay requires the raw export "
     "credential; a read credential gets 403.",
     ("restricted-needs-raw-credential",)),
)


# --- export-credential ------------------------------------------------------------------

EXPORT_CREDENTIAL = SliceSpec(
    package_name="oakridge-observation-export-credential",
    files={
        **_SOURCE_FILES,
        f"{_OBS}tests/ingest-auth.test.ts": "tests/visible/ingest-auth.test.ts",
        f"{_OBS}tests/database-fixture.ts": "tests/visible/database-fixture.ts",
        f"{_OBS}tests/export-redaction.test.ts": "tests/visible/export-redaction.test.ts",
        # Untouched here; it ships hidden only because the scenario needs a regression group.
        f"{_OBS}tests/classification.test.ts": _CLASSIFICATION_HIDDEN,
    },
    replacements=(
        *_SOURCE_REPLACEMENTS,
        Replacement("tests/visible/ingest-auth.test.ts", '"../src/', '"../../src/', 4),
        Replacement("tests/visible/ingest-auth.test.ts", 'from "canonical-json"', 'from "../../canonical-json/src/index"'),
        Replacement("tests/visible/export-redaction.test.ts", '"../src/', '"../../src/', 4),
        Replacement(_CLASSIFICATION_HIDDEN, '"../src/', '"../../../src/'),
    ),
    typecheck_include=_TYPECHECK,
)

_CREDENTIALS_TYPE: Edit = (
    "src/http/ingest-auth.ts",
    "  readonly grade?: readonly Credential[]; readonly export_raw?: readonly Credential[] }",
    "  readonly grade?: readonly Credential[]; readonly export?: readonly Credential[];\n"
    "  readonly export_raw?: readonly Credential[] }",
)
_ENV_PARSE_OLD = (
    "  const export_raw = configuredCredentials(env.OBSERVATION_EXPORT_RAW_CREDENTIALS);\n"
    "  const all = [...ingest, ...read, ...grade, ...export_raw];\n"
)
_ENV_RETURN_OLD = "  return { ingest, read, grade, export_raw };"
_ENV_RETURN: Edit = ("src/http/ingest-auth.ts", _ENV_RETURN_OLD, "  return { ingest, read, grade, export: exporting, export_raw };")


def _env_parse(unique: bool = True) -> Edit:
    listed = "...exporting, " if unique else ""
    return (
        "src/http/ingest-auth.ts",
        _ENV_PARSE_OLD,
        "  const exporting = configuredCredentials(env.OBSERVATION_EXPORT_CREDENTIALS);\n"
        "  const export_raw = configuredCredentials(env.OBSERVATION_EXPORT_RAW_CREDENTIALS);\n"
        f"  const all = [...ingest, ...read, ...grade, {listed}...export_raw];\n",
    )


_GATE_OLD = "    const tenant = rawCredential ?? credentialFor(authorization, deps.credentials.read);"


def _gate(accepted: str = "deps.credentials.export ?? []") -> Edit:
    return ("src/http/exports.ts", _GATE_OLD,
            f"    const tenant = rawCredential ?? credentialFor(authorization, {accepted});")


_CREDENTIAL_PATCHES: Patches = {
    "reference.patch": (
        "Parse the export credentials, keep their tokens unique, and gate exports on them instead of read credentials.",
        (_CREDENTIALS_TYPE, _env_parse(), _ENV_RETURN, _gate()),
    ),
    "unreachable-env.patch": (
        "The route accepts export credentials and the variable is parsed and checked, but the parsed list is dropped from the returned credentials, so a configured token never reaches the route.",
        (_CREDENTIALS_TYPE, _env_parse(), _gate()),
    ),
    "read-still-exports.patch": (
        "Export credentials work, but read credentials are still accepted for export.",
        (_CREDENTIALS_TYPE, _env_parse(), _ENV_RETURN, _gate("[...(deps.credentials.export ?? []), ...deps.credentials.read]")),
    ),
    "tokens-not-unique.patch": (
        "Export credentials work, but their tokens are left out of the cross-capability uniqueness check.",
        (_CREDENTIALS_TYPE, _env_parse(unique=False), _ENV_RETURN, _gate()),
    ),
}

_CREDENTIAL_REQUIREMENTS: Requirements = (
    ("credentialsFromEnv reads OBSERVATION_EXPORT_CREDENTIALS, in the same JSON format as the "
     "other credential variables, into the credentials' export list, which is empty when the "
     "variable is unset; a malformed value is refused.",
     ("env-parses-export", "env-unset-empty", "env-malformed")),
    ("POST /v1/exports/assay accepts an export credential configured that way, or a raw export "
     "credential, and refuses read credentials with 403.",
     ("env-token-exports", "export-token-passes", "read-token-refused", "raw-token-still-exports")),
    ("An export credential cannot request raw allowances; those still need the raw export "
     "credential.", ("export-token-no-raw",)),
    ("Export tokens must be unique across every capability, including raw export.",
     ("export-token-unique",)),
)


TASKS = (
    LibraryTask(
        scenario="restricted-evidence",
        slice=RESTRICTED_EVIDENCE,
        patches=_RESTRICTED_PATCHES,
        requirements=_RESTRICTED_REQUIREMENTS,
        feature_tokens=("restricted_content",),
        local_adaptations=(
            RELOCATION,
            _NUL_ESCAPE,
            HIDDEN_MOVE,
            "The two pinned assertions that brief.files_in_scope evidence classifies as internal "
            "are removed from the hidden regression copy of classification.test.ts, because the "
            "task reverses them; the reversed expectation is a hidden new-behavior check.",
        ),
    ),
    LibraryTask(
        scenario="export-credential",
        slice=EXPORT_CREDENTIAL,
        patches=_CREDENTIAL_PATCHES,
        requirements=_CREDENTIAL_REQUIREMENTS,
        feature_tokens=("OBSERVATION_EXPORT_CREDENTIALS",),
        local_adaptations=(
            RELOCATION,
            _NUL_ESCAPE,
            "classification.test.ts, unchanged, is the hidden regression group; this control "
            "moves no pinned test, because none points at the edit.",
        ),
    ),
)
