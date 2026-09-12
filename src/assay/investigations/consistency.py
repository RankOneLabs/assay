"""A local consistency investigation with explicit structural limits.

The ordinal records syntactic abstraction use, not functional correctness.
Only direct calls in the requested function receive automatic judgments;
indirection and unrecognized implementations need the configured judge.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import Any, Literal, Protocol

from pydantic import Field, field_validator, model_validator

from assay.execution import EvaluationFailed, EvaluationResult, EvaluationSuccess, Evaluator
from assay.models import (
    Arm,
    EvaluationCoordinate,
    EvaluatorDeclaration,
    Realization,
    StudySnapshot,
    Subject,
    WireModel,
)
from assay.repository import validate_repository
from assay.store import ObjectStore

CATEGORIES = ("duplicated", "mixed", "reused")
PAYLOAD_SCHEMA_ID = "https://assay.local/schemas/consistency-evidence-v1.json"


class FunctionalCase(WireModel):
    input: Any
    expected: Any


class CodingTask(WireModel):
    id: str
    family: Literal["cosmetic", "architectural", "semantic"]
    instruction: str
    helper: str
    primitives: tuple[str, ...] = Field(min_length=1)
    helper_source: str
    target_path: str = "module.py"
    test_cases: tuple[FunctionalCase, ...] = ()
    reused_source: str = ""
    duplicated_source: str = ""

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_primitive(cls, value: Any) -> Any:
        if isinstance(value, Mapping) and "primitive" in value and "primitives" not in value:
            value = dict(value)
            value["primitives"] = (value.pop("primitive"),)
        return value

    @field_validator("target_path")
    @classmethod
    def safe_target_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        module_parts = list(path.with_suffix("").parts)
        if module_parts and module_parts[0] == "src":
            module_parts.pop(0)
        if module_parts and module_parts[-1] == "__init__":
            module_parts.pop()
        if (
            not value
            or "\\" in value
            or path.is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or path.suffix != ".py"
            or not module_parts
            or any(not part.isidentifier() for part in module_parts)
        ):
            raise ValueError("target_path must be a relative Python file")
        return value


def _functional_cases(*values: dict[str, Any]) -> tuple[FunctionalCase, ...]:
    return tuple(FunctionalCase.model_validate(value) for value in values)


TASKS = (
    CodingTask(
        id="display-name",
        family="cosmetic",
        instruction="Add implement(value) returning a normalized display name.",
        helper="normalize_name",
        primitives=("strip", "title"),
        helper_source="def normalize_name(value):\n    return value.strip().title()\n",
        test_cases=_functional_cases(
            {"input": " alice smith ", "expected": "Alice Smith"},
            {"input": "mARY-jANE", "expected": "Mary-Jane"},
            {"input": "", "expected": ""},
        ),
        reused_source="def implement(value):\n    return normalize_name(value)\n",
        duplicated_source="def implement(value):\n    return value.strip().title()\n",
    ),
    CodingTask(
        id="record-decoding",
        family="architectural",
        instruction="Add implement(value) returning a decoded JSON record.",
        helper="decode_record",
        primitives=("json.loads",),
        helper_source="import json\ndef decode_record(value):\n    return json.loads(value)\n",
        test_cases=_functional_cases(
            {"input": '{"a":1}', "expected": {"a": 1}},
            {"input": "[true,null,3]", "expected": [True, None, 3]},
            {"input": '"text"', "expected": "text"},
        ),
        reused_source="def implement(value):\n    return decode_record(value)\n",
        duplicated_source="def implement(value):\n    return json.loads(value)\n",
    ),
    CodingTask(
        id="bounded-amount",
        family="semantic",
        instruction="Add implement(value) returning an integer amount clamped to zero or above.",
        helper="bounded_amount",
        primitives=("max", "int"),
        helper_source="def bounded_amount(value):\n    return max(0, int(value))\n",
        test_cases=_functional_cases(
            {"input": "12", "expected": 12},
            {"input": "-7", "expected": 0},
            {"input": "0", "expected": 0},
        ),
        reused_source="def implement(value):\n    return bounded_amount(value)\n",
        duplicated_source="def implement(value):\n    return max(0, int(value))\n",
    ),
)


EXPERIMENT_TASKS = (
    *TASKS,
    CodingTask(
        id="canonical-email",
        family="cosmetic",
        instruction="Add implement(value) returning an email trimmed and lowercased.",
        helper="normalize_email",
        primitives=("strip", "lower"),
        helper_source="def normalize_email(value):\n    return value.strip().lower()\n",
        test_cases=_functional_cases(
            {"input": " Alice.Example@EXAMPLE.COM ", "expected": "alice.example@example.com"},
            {"input": "A+B@X.IO", "expected": "a+b@x.io"},
            {"input": "", "expected": ""},
        ),
        reused_source="def implement(value):\n    return normalize_email(value)\n",
        duplicated_source="def implement(value):\n    return value.strip().lower()\n",
    ),
    CodingTask(
        id="compact-whitespace",
        family="cosmetic",
        instruction=(
            "Add implement(value) returning whitespace-separated words joined by one space."
        ),
        helper="compact_whitespace",
        primitives=("split", "join"),
        helper_source='def compact_whitespace(value):\n    return " ".join(value.split())\n',
        test_cases=_functional_cases(
            {"input": " alpha   beta ", "expected": "alpha beta"},
            {"input": "a\tb\nc", "expected": "a b c"},
            {"input": "   ", "expected": ""},
        ),
        reused_source="def implement(value):\n    return compact_whitespace(value)\n",
        duplicated_source='def implement(value):\n    return " ".join(value.split())\n',
    ),
    CodingTask(
        id="canonical-code",
        family="cosmetic",
        instruction="Add implement(value) returning a code trimmed and uppercased.",
        helper="canonical_code",
        primitives=("strip", "upper"),
        helper_source="def canonical_code(value):\n    return value.strip().upper()\n",
        test_cases=_functional_cases(
            {"input": " ab-12 ", "expected": "AB-12"},
            {"input": "xYz", "expected": "XYZ"},
            {"input": "", "expected": ""},
        ),
        reused_source="def implement(value):\n    return canonical_code(value)\n",
        duplicated_source="def implement(value):\n    return value.strip().upper()\n",
    ),
    CodingTask(
        id="record-encoding",
        family="architectural",
        instruction="Add implement(value) returning compact JSON with object keys sorted.",
        helper="encode_record",
        primitives=("json.dumps",),
        helper_source=(
            "import json\n"
            "def encode_record(value):\n"
            '    return json.dumps(value, sort_keys=True, separators=(",", ":"))\n'
        ),
        test_cases=_functional_cases(
            {"input": {"b": 2, "a": 1}, "expected": '{"a":1,"b":2}'},
            {"input": [True, None, 3], "expected": "[true,null,3]"},
            {"input": {}, "expected": "{}"},
        ),
        reused_source="def implement(value):\n    return encode_record(value)\n",
        duplicated_source=(
            "def implement(value):\n"
            '    return json.dumps(value, sort_keys=True, separators=(",", ":"))\n'
        ),
    ),
    CodingTask(
        id="integer-parsing",
        family="architectural",
        instruction=(
            "Add implement(value) returning the base-10 integer represented by the trimmed value."
        ),
        helper="parse_integer",
        primitives=("strip", "int"),
        helper_source="def parse_integer(value):\n    return int(value.strip(), 10)\n",
        test_cases=_functional_cases(
            {"input": " 42 ", "expected": 42},
            {"input": "-9", "expected": -9},
            {"input": "0010", "expected": 10},
        ),
        reused_source="def implement(value):\n    return parse_integer(value)\n",
        duplicated_source="def implement(value):\n    return int(value.strip(), 10)\n",
    ),
    CodingTask(
        id="comma-fields",
        family="architectural",
        instruction=(
            "Add implement(value) returning the fields produced by splitting value at commas."
        ),
        helper="split_fields",
        primitives=("split",),
        helper_source='def split_fields(value):\n    return value.split(",")\n',
        test_cases=_functional_cases(
            {"input": "a,b,c", "expected": ["a", "b", "c"]},
            {"input": "one", "expected": ["one"]},
            {"input": ",", "expected": ["", ""]},
        ),
        reused_source="def implement(value):\n    return split_fields(value)\n",
        duplicated_source='def implement(value):\n    return value.split(",")\n',
    ),
    CodingTask(
        id="clamped-percentage",
        family="semantic",
        instruction=(
            "Add implement(value) returning an integer clamped between zero and one hundred."
        ),
        helper="clamp_percentage",
        primitives=("min", "max", "int"),
        helper_source="def clamp_percentage(value):\n    return min(100, max(0, int(value)))\n",
        test_cases=_functional_cases(
            {"input": "40", "expected": 40},
            {"input": "-3", "expected": 0},
            {"input": "140", "expected": 100},
        ),
        reused_source="def implement(value):\n    return clamp_percentage(value)\n",
        duplicated_source="def implement(value):\n    return min(100, max(0, int(value)))\n",
    ),
    CodingTask(
        id="even-integer",
        family="semantic",
        instruction="Add implement(value) returning whether value represents an even integer.",
        helper="is_even_integer",
        primitives=("int",),
        helper_source="def is_even_integer(value):\n    return int(value) % 2 == 0\n",
        test_cases=_functional_cases(
            {"input": "2", "expected": True},
            {"input": "-3", "expected": False},
            {"input": "0", "expected": True},
        ),
        reused_source="def implement(value):\n    return is_even_integer(value)\n",
        duplicated_source="def implement(value):\n    return int(value) % 2 == 0\n",
    ),
    CodingTask(
        id="absolute-amount",
        family="semantic",
        instruction="Add implement(value) returning the absolute integer amount.",
        helper="absolute_amount",
        primitives=("abs", "int"),
        helper_source="def absolute_amount(value):\n    return abs(int(value))\n",
        test_cases=_functional_cases(
            {"input": "12", "expected": 12},
            {"input": "-7", "expected": 7},
            {"input": "0", "expected": 0},
        ),
        reused_source="def implement(value):\n    return absolute_amount(value)\n",
        duplicated_source="def implement(value):\n    return abs(int(value))\n",
    ),
)


class AmbiguityJudge(Protocol):
    def configuration(self) -> dict[str, Any]: ...

    async def judge(self, *, task: CodingTask, source: str) -> EvaluationResult: ...


def parse_candidate_source(
    source: str, *, helper: str, target_path: str
) -> tuple[ast.Module, ast.FunctionDef]:
    """Accept only imports and one inertly declared implement function."""
    tree = ast.parse(source)
    body = list(tree.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body.pop(0)
    imports: list[ast.Import | ast.ImportFrom] = []
    while body and isinstance(body[0], ast.Import | ast.ImportFrom):
        statement = body.pop(0)
        assert isinstance(statement, ast.Import | ast.ImportFrom)
        imports.append(statement)
    if len(body) != 1 or not isinstance(body[0], ast.FunctionDef):
        raise ValueError("source must contain only imports and one implement function")
    function = body[0]
    if function.name != "implement":
        raise ValueError("the sole function must be named implement")
    if function.decorator_list or function.args.defaults or any(function.args.kw_defaults):
        raise ValueError("implement decorators and default expressions are not allowed")
    arguments = (
        *function.args.posonlyargs,
        *function.args.args,
        *function.args.kwonlyargs,
    )
    annotations = [argument.annotation for argument in arguments if argument.annotation is not None]
    if function.returns is not None:
        annotations.append(function.returns)
    if any(not isinstance(annotation, ast.Name | ast.Constant) for annotation in annotations):
        raise ValueError("only simple name or string annotations are allowed")
    bound_names: set[str] = set()
    for statement in imports:
        for alias in statement.names:
            if alias.name == "*":
                raise ValueError("wildcard imports are not allowed")
            bound_names.add(alias.asname or alias.name.split(".", 1)[0])
    if bound_names & {helper, "implement"}:
        raise ValueError("imports must not replace the repository helper or implement")
    target = PurePosixPath(target_path)
    target_parts = list(target.with_suffix("").parts)
    if target_parts and target_parts[0] == "src":
        target_parts.pop(0)
    target_is_package = bool(target_parts and target_parts[-1] == "__init__")
    if target_is_package:
        target_parts.pop()
    target_module = ".".join(target_parts)
    package_parts = target_parts if target_is_package else target_parts[:-1]
    for statement in imports:
        if isinstance(statement, ast.Import):
            imports_target = any(alias.name == target_module for alias in statement.names)
        else:
            if statement.level:
                retained = len(package_parts) - (statement.level - 1)
                base_parts = package_parts[: max(0, retained)]
                if statement.module:
                    base_parts.extend(statement.module.split("."))
                imported_module = ".".join(base_parts)
            else:
                imported_module = statement.module or ""
            imports_target = imported_module == target_module or any(
                f"{imported_module}.{alias.name}" == target_module for alias in statement.names
            )
        if imports_target:
            raise ValueError("imports from the target module are not allowed")
    return tree, function


def _import_origins(tree: ast.Module) -> dict[str, str]:
    origins: dict[str, str] = {}
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                bound = alias.asname or alias.name.split(".", 1)[0]
                origins[bound] = alias.name if alias.asname else bound
        elif isinstance(statement, ast.ImportFrom):
            module = "." * statement.level + (statement.module or "")
            for alias in statement.names:
                if alias.name != "*":
                    origins[alias.asname or alias.name] = f"{module}.{alias.name}"
    return origins


def _call_origin(node: ast.expr, origins: Mapping[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return origins.get(node.id, node.id)
    if not isinstance(node, ast.Attribute):
        return None
    attributes = [node.attr]
    value = node.value
    while isinstance(value, ast.Attribute):
        attributes.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name) and value.id in origins:
        return ".".join((origins[value.id], *reversed(attributes)))
    return node.attr


class StructuralEvaluator:
    def __init__(self, judge: AmbiguityJudge | None = None) -> None:
        self.judge = judge

    def configuration(self) -> dict[str, Any]:
        return {
            "id": "consistency-structure",
            "version": "4",
            "categories": list(CATEGORIES),
            "target_function": "implement",
            "accepted_module": "optional-docstring-then-imports-then-one-function",
            "accepted_function": "optional-docstring-then-one-return-for-automatic-verdict",
            "judge": None if self.judge is None else self.judge.configuration(),
        }

    async def evaluate(
        self, *, input_value: Any, output: Any, coordinate: EvaluationCoordinate
    ) -> EvaluationResult:
        del coordinate
        try:
            task = CodingTask.model_validate(input_value["task"])
            source = output["source"]
            if not isinstance(source, str):
                raise ValueError("worker output source must be a string")
            tree, function = parse_candidate_source(
                source, helper=task.helper, target_path=task.target_path
            )
        except (KeyError, TypeError, ValueError, SyntaxError) as error:
            return EvaluationFailed("InvalidOutput", str(error))
        # Limit automatic classification to straight-line return expressions.
        # Calls hidden in branches, nested functions, or aliases need adjudication.
        function_body = list(function.body)
        if (
            function_body
            and isinstance(function_body[0], ast.Expr)
            and isinstance(function_body[0].value, ast.Constant)
            and isinstance(function_body[0].value.value, str)
        ):
            function_body.pop(0)
        statement = function_body[0] if len(function_body) == 1 else None
        expression = statement.value if isinstance(statement, ast.Return) else None
        nodes = list(ast.walk(expression)) if expression is not None else []
        # ast.walk also visits deferred or conditional expressions: a helper
        # inside a returned lambda/generator need not execute at all.
        indirect = any(
            isinstance(
                node,
                ast.Lambda
                | ast.GeneratorExp
                | ast.ListComp
                | ast.SetComp
                | ast.DictComp
                | ast.IfExp
                | ast.BoolOp,
            )
            for node in nodes
        )
        straight = expression is not None and not indirect
        calls = [node.func for node in nodes if isinstance(node, ast.Call)]
        origins = _import_origins(ast.parse(task.helper_source))
        origins.update(_import_origins(tree))
        call_origins = [_call_origin(node, origins) for node in calls]
        names = {name for name in call_origins if name is not None}
        helper_used = task.helper in names
        primitives_used = sorted(names.intersection(task.primitives))
        allowed_calls = {*task.primitives, task.helper}
        unknown_call = any(name not in allowed_calls for name in call_origins)
        straight = straight and not unknown_call
        detail = {"route": "structural", "calls": sorted(names), "family": task.family}
        if straight and (helper_used or primitives_used):
            verdict = (
                "mixed"
                if helper_used and primitives_used
                else ("reused" if helper_used else "duplicated")
            )
            return EvaluationSuccess(verdict, ("direct_call_structure",), detail)
        if self.judge is None:
            return EvaluationFailed("AmbiguousStructure", "no ambiguity judge configured", detail)
        try:
            result = await self.judge.judge(task=task, source=source)
        except Exception as error:
            return EvaluationFailed(type(error).__name__, str(error), detail)
        if not isinstance(result, EvaluationSuccess | EvaluationFailed):
            return EvaluationFailed("InvalidJudgeResult", "judge must return an EvaluationResult")
        if isinstance(result, EvaluationSuccess) and result.verdict not in CATEGORIES:
            return EvaluationFailed(
                "InvalidJudgeVerdict",
                "judge category is not declared",
                detail=result.detail,
                accounting=result.accounting,
            )
        if isinstance(result, EvaluationFailed):
            return result
        return EvaluationSuccess(
            result.verdict,
            (*result.reason_codes, "ambiguous_judge"),
            {"route": "judge", "structural": detail, "judge": result.detail},
            result.accounting,
        )


def _payload_schema(schema_id: str, categories: tuple[str, ...]) -> dict[str, Any]:
    ref = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
    fields: dict[str, Any] = {
        key: {"type": "string", "minLength": 1}
        for key in ("run_id", "cell_id", "evaluator_id", "arm_id")
    }
    fields.update(
        plan_ref=ref,
        base_subject_ref=ref,
        worker_repeat={"type": "integer", "minimum": 0},
        evaluator_repeat={"type": "integer", "minimum": 0},
        detail_refs={"type": "array", "items": ref, "uniqueItems": True},
    )
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": schema_id,
        "allOf": [
            {"$ref": "https://paa.dev/paa-evidence-record.schema.json"},
            {
                "properties": {
                    "verdict": {"properties": {"value": {"enum": list(categories)}}},
                    "payload": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": list(fields),
                        "properties": fields,
                    },
                }
            },
        ],
    }


def materialize_consistency(
    store: ObjectStore,
    *,
    worker_configuration: dict[str, Any],
    evaluator: StructuralEvaluator,
    schemas: Mapping[str, dict[str, Any]],
    tasks: Sequence[CodingTask] = TASKS,
    evaluator_repeats: int = 2,
    correctness_evaluator: Evaluator | None = None,
    execution_schedule: str | None = None,
    repository_variants: Mapping[str, Mapping[str, Mapping[str, str]]] | None = None,
) -> StudySnapshot:
    """Freeze local task/repository inputs and supplied PAA contracts without providers."""
    if repository_variants is not None:
        task_ids = {task.id for task in tasks}
        if set(repository_variants) != task_ids or any(
            set(repository_variants[task_id]) != {"clean", "inconsistent"}
            for task_id in task_ids
        ):
            raise ValueError("repository variants must exactly cover every task and arm")
    basis_ref = str(
        store.publish_json(
            {
                "categories": list(CATEGORIES),
                "definition": (
                    "Direct helper reuse; mixed includes calls to any primitive used by the helper."
                ),
                "ambiguous": "Judge when direct, unconditional call structure cannot decide; "
                "deferred and conditional expressions are ambiguous.",
            }
        )
    )
    identity = {
        "property": "abstraction_use",
        "target": "output",
        "technique": "deterministic" if evaluator.judge is None else "llm_judge",
        "evaluation_basis": {"kind": "rubric", "ref": basis_ref},
        "epistemic_status": "proxy",
        "version": "2",
        "authority": "advisory",
    }
    declaration = EvaluatorDeclaration(
        id="abstraction",
        identity=identity,
        payload_schema=PAYLOAD_SCHEMA_ID,
        payload_schema_ref=str(store.publish_json(_payload_schema(PAYLOAD_SCHEMA_ID, CATEGORIES))),
        basis_ref=basis_ref,
        configuration=evaluator.configuration(),
        repeats=evaluator_repeats,
    )
    declarations = [declaration]
    identities: list[dict[str, Any]] = [identity]
    if correctness_evaluator is not None:
        correctness_categories = ("incorrect", "correct")
        correctness_schema_id = (
            "https://assay.local/schemas/consistency-correctness-evidence-v1.json"
        )
        correctness_basis_ref = str(
            store.publish_json(
                {
                    "categories": list(correctness_categories),
                    "definition": "All hidden deterministic task cases pass in the pinned sandbox.",
                    "comparison": "Canonical JSON equality of returned and expected values.",
                    "scope": "Finite test-case correctness; not a proof over all possible inputs.",
                }
            )
        )
        correctness_identity = {
            "property": "functional_correctness",
            "target": "output",
            "technique": "deterministic",
            "evaluation_basis": {"kind": "invariant", "ref": correctness_basis_ref},
            "epistemic_status": "proxy",
            "version": "1",
            "authority": "advisory",
        }
        declarations.append(
            EvaluatorDeclaration(
                id="correctness",
                identity=correctness_identity,
                payload_schema=correctness_schema_id,
                payload_schema_ref=str(
                    store.publish_json(
                        _payload_schema(correctness_schema_id, correctness_categories)
                    )
                ),
                basis_ref=correctness_basis_ref,
                configuration=correctness_evaluator.configuration(),
                repeats=1,
            )
        )
        identities.append(correctness_identity)
    paa_task = {
        "task": "code_consistency",
        "version": 1,
        "description": (
            "Measure abstraction use with varied repository consistency"
            + (
                " and finite-case functional correctness."
                if correctness_evaluator is not None
                else "."
            )
        ),
        "boundary": {"input": "coding_task_repository", "output": "implementation_source"},
        "initial_position": "manual",
        "deployment": "shadow",
        "evaluators": identities,
        "position_policy": {"manual": "offline", "hitl": "blocking"},
        "promotion": {
            "from": "manual",
            "to": "hitl",
            "report": "consistency_report",
            "window": {"kind": "cases", "size": 10},
            "execution": "operator_approval",
        },
        "demotion": {
            "from": "hitl",
            "to": "manual",
            "trigger": "operator_decision",
            "window": {"kind": "cases", "size": 1},
        },
    }
    conditions = (
        {} if execution_schedule is None else {"assay_execution_schedule": execution_schedule}
    )
    arms = tuple(
        Arm(
            id=arm,
            worker=worker_configuration,
            intervention={"repository": arm},
            conditions=conditions,
        )
        for arm in ("clean", "inconsistent")
    )
    subjects = []
    realizations = []
    for task in tasks:
        task_value = task.model_dump(mode="json", exclude={"reused_source", "duplicated_source"})
        subject_ref = str(store.publish_json(task_value))
        subjects.append(
            Subject(
                id=task.id,
                label=task.instruction,
                partition=task.family,
                digest=subject_ref,
                payload_ref=subject_ref,
            )
        )
        for arm in arms:
            if repository_variants is None:
                example = task.reused_source if arm.id == "clean" else task.duplicated_source
                repository = {
                    task.target_path: (
                        task.helper_source
                        + "\n"
                        + example.replace("implement", "existing_feature")
                    )
                }
            else:
                try:
                    repository = validate_repository(repository_variants[task.id][arm.id])
                except KeyError as error:
                    raise ValueError(
                        f"missing {arm.id} repository for task {task.id}"
                    ) from error
                if task.target_path not in repository:
                    raise ValueError(f"target file missing for task {task.id}")
            artifact_ref = str(
                store.publish_json(
                    {
                        "task": task_value,
                        "repository": repository,
                        "base_subject_ref": subject_ref,
                    }
                )
            )
            realizations.append(
                Realization(
                    subject_id=task.id,
                    arm_id=arm.id,
                    digest=artifact_ref,
                    artifact_ref=artifact_ref,
                )
            )
    return StudySnapshot(
        subjects=tuple(subjects),
        arms=arms,
        realizations=tuple(realizations),
        evaluators=tuple(declarations),
        paa_task_ref=str(store.publish_json(paa_task)),
        task_schema_ref=str(store.publish_json(schemas["paa-task"])),
        evidence_schema_ref=str(store.publish_json(schemas["paa-evidence-record"])),
        operating_schema_ref=str(store.publish_json(schemas["paa-operating-record"])),
        pricing_catalog_ref=str(store.publish_json({"prices": [], "coverage": "unavailable"})),
    )
