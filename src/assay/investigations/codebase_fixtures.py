# ruff: noqa: E501
"""DRY scenarios set in snapshots of our own codebases instead of samples.

Each family is one slice of a public repository of ours, copied byte for byte
from one commit by ``experiments/consistency_pilot/snapshot_codebases.py``:

* ``jig-llm``: jig's LLM adapters. Target: a new vLLM adapter module.
* ``jig-feedback``: jig's graders, score persistence and SQLite tracers.
  Targets: a new rubric grader and a new JSON Lines tracer.
* ``scout-platforms``: scout's platform scanning adapters. Target: a new
  Mastodon adapter module.

Every task needs behaviour one of the slice's shared helpers already
provides. The clean arm is the code as it is, where the existing callers use
the helper; in the inconsistent arm those callers inline its logic instead.
The helper and the target file are identical in both arms.

Package ``__init__`` files that would import the rest of a repository are not
in the snapshots; every package gets an empty one instead.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from textwrap import dedent, indent
from typing import Any

from assay.investigations.consistency import CodingTask, FunctionalCase

_SNAPSHOTS = Path(__file__).with_name("snapshots")


def _load(name: str) -> dict[str, Any]:
    snapshot: dict[str, Any] = json.loads((_SNAPSHOTS / f"{name}.json").read_text(encoding="utf-8"))
    return snapshot


SNAPSHOTS: dict[str, dict[str, Any]] = {
    name: _load(name) for name in ("jig-llm", "jig-feedback", "scout-platforms")
}


def _source(text: str) -> str:
    return dedent(text).lstrip("\n")


def _cases(*values: tuple[Any, Any]) -> tuple[FunctionalCase, ...]:
    return tuple(FunctionalCase(input=given, expected=expected) for given, expected in values)


def _replace(text: str, old: str, new: str, count: int = 1) -> str:
    if text.count(old) != count:
        raise ValueError(f"expected {count} of {old!r}, found {text.count(old)}")
    return text.replace(old, new)


def _inline(text: str, pattern: str, block: Callable[[re.Match[str]], str], count: int) -> str:
    """Replace each whole-line statement matching ``pattern`` with ``block``.

    The block is indented like the statement it replaces.
    """
    regex = re.compile(rf"^( *){pattern}\n", re.MULTILINE | re.DOTALL)
    replaced, found = regex.subn(lambda match: indent(block(match), match.group(1)), text)
    if found != count:
        raise ValueError(f"expected {count} statements matching {pattern!r}, found {found}")
    return replaced


def _edit(files: dict[str, str], path: str, *edits: Callable[[str], str]) -> None:
    text = files[path]
    for edit in edits:
        text = edit(text)
    files[path] = text


def _sub(old: str, new: str, count: int = 1) -> Callable[[str], str]:
    return lambda text: _replace(text, old, new, count)


def _lines(
    pattern: str, block: str | Callable[[re.Match[str]], str], count: int
) -> Callable[[str], str]:
    render = block if callable(block) else (lambda _match: block)
    return lambda text: _inline(text, pattern, render, count)


def _helper_source(path: str, text: str, helper: str) -> str:
    for node in ast.parse(text).body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == helper:
            segment = ast.get_source_segment(text, node)
            assert segment is not None
            return segment
    raise ValueError(f"{helper} is not defined in {path}")


def _module(path: str) -> str:
    parts = PurePosixPath(path).with_suffix("").parts
    return ".".join(parts[1:] if parts[0] == "src" else parts)


# --- jig-llm ----------------------------------------------------------------

_VLLM = _source(
    '''
    """vLLM adapter — OpenAI-compatible chat completions served by vLLM.

    vLLM's server speaks the OpenAI chat-completions protocol, including tool
    calling and ``response_format`` guided decoding. It has no request field for
    switching a model's reasoning mode on or off, and reports no cost.
    """
    from __future__ import annotations

    import logging
    from typing import Any

    from jig.core.errors import JigLLMError, UnsupportedReasoningError, UnsupportedResponseFormatError
    from jig.core.types import CompletionParams, Message, Role, ToolCall, Usage

    logger = logging.getLogger(__name__)
    '''
)


def _merge_block(target: str, *, response_format: str, reasoning: str) -> str:
    return _source(
        f"""
        if {reasoning}:
            raise UnsupportedReasoningError("This adapter does not support reasoning control")
        if params.temperature is not None:
            {target}["temperature"] = params.temperature
        if params.max_tokens is not None:
            {target}["max_tokens"] = params.max_tokens
        if params.response_format is not None:
        {indent(response_format, "    ")}
        if params.provider_params:
            {target}.update(params.provider_params)
        """
    )


def _inline_tool_arguments(files: dict[str, str]) -> None:
    drop_import = _sub("from jig.llm._parsing import parse_tool_arguments\n", "")
    _edit(
        files,
        "src/jig/llm/openai.py",
        drop_import,
        _sub(
            "arguments=parse_tool_arguments(tc.function.arguments, self._provider_label),",
            'arguments=json.loads(tc.function.arguments or "{}"),',
        ),
    )
    _edit(
        files,
        "src/jig/llm/ollama.py",
        drop_import,
        _sub("import logging\nimport uuid\n", "import json\nimport logging\nimport uuid\n"),
        _sub(
            'arguments=parse_tool_arguments(tc.function.arguments, "ollama"),',
            "arguments=(\n"
            "                                tc.function.arguments\n"
            "                                if isinstance(tc.function.arguments, dict)\n"
            '                                else json.loads(tc.function.arguments or "{}")\n'
            "                            ),",
        ),
    )
    _edit(
        files,
        "src/jig/llm/dispatch.py",
        drop_import,
        _sub(
            "    is model intent that failed to serialize — that raises a retryable\n"
            "    :class:`JigLLMError` via the shared ``parse_tool_arguments`` helper\n"
            "    (the same semantics every other adapter has), so the runner's retry\n"
            "    path surfaces the failure to the model instead of the call silently\n"
            '    vanishing and the turn reading as "no tool calls".\n',
            "    is model intent that failed to serialize — that raises, so the\n"
            "    failure surfaces instead of the call silently vanishing and the turn\n"
            '    reading as "no tool calls".\n',
        ),
        _sub(
            "        calls.append(ToolCall(\n"
            '            id=entry.get("id") or f"call_{uuid.uuid4().hex[:12]}",\n'
            "            name=name,\n"
            '            arguments=parse_tool_arguments(fn.get("arguments"), "dispatch"),\n',
            '        raw_arguments = fn.get("arguments") or "{}"\n'
            "        calls.append(ToolCall(\n"
            '            id=entry.get("id") or f"call_{uuid.uuid4().hex[:12]}",\n'
            "            name=name,\n"
            "            arguments=raw_arguments if isinstance(raw_arguments, dict) else json.loads(raw_arguments),\n",
        ),
    )


def _inline_error_wrapping(files: dict[str, str]) -> None:
    _edit(
        files,
        "src/jig/llm/anthropic.py",
        _sub(
            "from jig.llm._common import merge_completion_kwargs, start_timer, wrap_llm_error\n",
            "from jig.llm._common import merge_completion_kwargs, start_timer\n",
        ),
        _sub(
            'raise wrap_llm_error(e, "anthropic") from e',
            'raise JigLLMError(str(e), "anthropic", status_code=getattr(e, "status_code", None)) from e',
        ),
    )
    _edit(
        files,
        "src/jig/llm/openai.py",
        _sub("    wrap_llm_error,\n", ""),
        _sub(
            "err = wrap_llm_error(e, self._provider_label)\n",
            "err = JigLLMError(\n"
            '                str(e), self._provider_label, status_code=getattr(e, "status_code", None)\n'
            "            )\n",
        ),
    )


def _inline_completion_kwargs(files: dict[str, str]) -> None:
    call = r"merge_completion_kwargs\(.*?\)"
    _edit(
        files,
        "src/jig/llm/anthropic.py",
        _sub(
            "from jig.llm._common import merge_completion_kwargs, start_timer, wrap_llm_error\n",
            "from jig.llm._common import start_timer, wrap_llm_error\n",
        ),
        _lines(
            call,
            _merge_block(
                "kwargs",
                response_format='raise UnsupportedResponseFormatError("This adapter does not support response_format")',
                reasoning="params.reasoning is not None",
            ),
            2,
        ),
    )
    _edit(
        files,
        "src/jig/llm/openai.py",
        _sub("    merge_completion_kwargs,\n", ""),
        _sub(
            "    # forwarded unchanged in complete()/stream() via merge_completion_kwargs.\n",
            "    # forwarded unchanged in complete()/stream().\n",
        ),
        _sub(
            "(``merge_completion_kwargs`` has already rejected a non-None value",
            "(``complete()`` has already rejected a non-None value",
        ),
        _lines(
            call,
            _merge_block(
                "kwargs",
                response_format='kwargs["response_format"] = params.response_format',
                reasoning="params.reasoning is not None and not self.supports_reasoning",
            ),
            2,
        ),
    )
    _edit(
        files,
        "src/jig/llm/dispatch.py",
        _sub(
            "from jig.llm._common import merge_completion_kwargs, start_timer\n",
            "from jig.llm._common import start_timer\n",
        ),
        _sub(
            "from jig.core.errors import JigLLMError\n",
            "from jig.core.errors import JigLLMError, UnsupportedReasoningError\n",
        ),
        _lines(
            call,
            _merge_block(
                "payload",
                response_format='payload["response_format"] = params.response_format',
                reasoning="params.reasoning is not None",
            ),
            1,
        ),
    )


def _inline_cost_stamping(files: dict[str, str]) -> None:
    def block(match: re.Match[str]) -> str:
        return (
            "if usage.cost is None:\n"
            f"    usage.cost = compute_cost({match.group(2)}, usage.input_tokens, usage.output_tokens)\n"
        )

    for path in ("src/jig/llm/anthropic.py", "src/jig/llm/openai.py", "src/jig/llm/google.py"):
        _edit(
            files,
            path,
            _sub(
                "from jig.llm.pricing import stamp_cost\n",
                "from jig.llm.pricing import compute_cost\n",
            ),
            _lines(r"stamp_cost\(usage, ([^)]*)\)", block, 1),
        )


# --- jig-feedback -------------------------------------------------------------

_RUBRIC_JUDGE = _source(
    '''
    """RubricJudge: an LLM grader that scores a response against a rubric.

    The judge model is asked for one JSON object mapping each rubric criterion
    to a score in [0, 1]; each criterion becomes one Score dimension.
    """
    from __future__ import annotations

    import json
    from typing import Any

    from jig.core.errors import GradeParseError
    from jig.core.types import CompletionParams, LLMClient, Message, Role, Score, ScoreSource
    '''
)

_JSONL_TRACER = _source(
    '''
    """JSONLTracer: append finished spans to a JSON Lines file, one per line.

    Timestamps are written as ISO strings and parsed back when a trace is read.
    """
    from __future__ import annotations

    import json
    from pathlib import Path
    from typing import Any

    from jig.core.types import Span, SpanKind, TracingLogger, Usage
    '''
)


def _inline_fence_stripping(files: dict[str, str]) -> None:
    block = _source(
        """
        text = response.content.strip()
        if text.startswith("```"):
            text = text.split("\\n", 1)[-1].rsplit("```", 1)[0]
        data = json.loads(text)
        """
    )
    for path in ("src/jig/feedback/llm_judge.py", "src/jig/feedback/judge_variants.py"):
        _edit(
            files,
            path,
            _sub("from jig.feedback.parsing import strip_markdown_fence\n", ""),
            _lines(
                re.escape("data = json.loads(strip_markdown_fence(response.content))"), block, 1
            ),
        )


def _inline_score_validation(files: dict[str, str]) -> None:
    block = _source(
        """
        if not scores:
            raise ValueError("scores must be non-empty")
        for s in scores:
            if not s.dimension or not 0.0 <= float(s.value) <= 1.0:
                raise ValueError(f"invalid score {s.value!r} for dimension {s.dimension!r}")
        """
    )
    for path in (
        "src/jig/core/grading.py",
        "src/jig/feedback/llm_judge.py",
        "src/jig/feedback/loop.py",
    ):
        _edit(
            files,
            path,
            _sub("from jig.feedback.validation import validate_scores\n", ""),
            _lines(re.escape("validate_scores(scores)"), block, 1),
        )


def _inline_utc_parsing(files: dict[str, str]) -> None:
    def naive_as_local(count: int) -> Callable[[str], str]:
        def edit(text: str) -> str:
            replaced, found = re.subn(
                r"parse_aware_utc\(([^)]*)\)", r"datetime.fromisoformat(\1).astimezone(UTC)", text
            )
            if found != count:
                raise ValueError(f"expected {count} parse_aware_utc calls, found {found}")
            return replaced

        return edit

    _edit(
        files,
        "src/jig/tracing/sqlite.py",
        _sub(
            "from jig._sqlite import LazyConnection, json_loads, parse_aware_utc\n",
            "from jig._sqlite import LazyConnection, json_loads\n",
        ),
        _sub(
            "# A naive input is treated as UTC, matching parse_aware_utc's",
            "# A naive input is treated as UTC, matching the reader's",
        ),
        naive_as_local(2),
    )
    _edit(
        files,
        "src/jig/tracing/federated.py",
        _sub("from jig._sqlite import parse_aware_utc\n", ""),
        _sub("from datetime import datetime\n", "from datetime import UTC, datetime\n"),
        naive_as_local(2),
    )
    _edit(
        files,
        "src/jig/feedback/loop.py",
        _sub(
            "from jig._sqlite import LazyConnection, json_dumps, json_loads, parse_aware_utc\n",
            "from jig._sqlite import LazyConnection, json_dumps, json_loads\n",
        ),
        naive_as_local(3),
    )


# --- scout-platforms ------------------------------------------------------------

_MASTODON = _source(
    '''
    """Mastodon API wrapper for fetching statuses from hashtag and account timelines."""

    from __future__ import annotations

    import logging
    from collections.abc import Mapping, Sequence
    from datetime import UTC, datetime

    import httpx

    from scout.errors import PlatformFetchFailure, PlatformFetchSuccess, SourceFetchOutcome
    from scout.platforms.base import SourceDescriptor
    from scout.result import Err, Ok, Result

    logger = logging.getLogger(__name__)
    '''
)

_ADAPTERS = (
    "src/scout/platforms/bluesky.py",
    "src/scout/platforms/farcaster.py",
)


def _inline_source_keys(files: dict[str, str]) -> None:
    key = (
        'f"{descriptor.platform.strip().casefold()}:'
        "{descriptor.source_kind.strip().casefold()}:"
        '{descriptor.provider_key.strip().casefold()}"'
    )
    _edit(
        files,
        "src/scout/platforms/discord.py",
        _sub(
            "from scout.platforms.base import SourceDescriptor, derive_source_key, source_since\n",
            "from scout.platforms.base import SourceDescriptor, source_since\n",
        ),
        _sub("source_key=derive_source_key(descriptor),", f"source_key={key},"),
    )
    for path in _ADAPTERS:
        _edit(
            files,
            path,
            _sub("    derive_source_key,\n", ""),
            _sub("source_key=derive_source_key(descriptor),", f"source_key={key},"),
        )


def _inline_source_boundaries(files: dict[str, str]) -> None:
    def resume(count: int) -> Callable[[str], str]:
        def edit(text: str) -> str:
            replaced, found = re.subn(
                r"source_since\(\s*descriptor, since, source_checkpoints\s*\)",
                "(\n"
                "    since if source_checkpoints is None\n"
                "    else source_checkpoints.get(derive_source_key(descriptor))\n"
                ")",
                text,
            )
            if found != count:
                raise ValueError(f"expected {count} source_since calls, found {found}")
            return replaced

        return edit

    _edit(
        files,
        "src/scout/platforms/discord.py",
        _sub(
            "from scout.platforms.base import SourceDescriptor, derive_source_key, source_since\n",
            "from scout.platforms.base import SourceDescriptor, derive_source_key\n",
        ),
        resume(1),
    )
    _edit(files, "src/scout/platforms/bluesky.py", _sub("    source_since,\n", ""), resume(2))
    _edit(files, "src/scout/platforms/farcaster.py", _sub("    source_since,\n", ""), resume(3))


def _inline_timestamp_parsing(files: dict[str, str]) -> None:
    def returned(match: re.Match[str]) -> str:
        return _source(
            f"""
            raw = str({match.group(2)})
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                return None
            return dt if dt.tzinfo is not None else None
            """
        )

    assigned = _source(
        """
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            dt = None
        if dt is not None and dt.tzinfo is None:
            dt = None
        """
    )
    for path in _ADAPTERS:
        _edit(
            files,
            path,
            _sub("    parse_platform_ts,\n", ""),
            _lines(r"return parse_platform_ts\(str\((.*?)\)\)", returned, 1),
            _lines(re.escape("dt = parse_platform_ts(raw)"), assigned, 1),
        )


def _inline_retry_after(files: dict[str, str]) -> None:
    block = _source(
        """
        delay = None
        if retry_after:
            try:
                delay = float(retry_after)
            except ValueError:
                delay = (parsedate_to_datetime(retry_after) - self._clock()).total_seconds()
        """
    )
    for path in _ADAPTERS:
        _edit(
            files,
            path,
            _sub("    parse_retry_after,\n", ""),
            _sub(
                "from datetime import UTC, datetime\n",
                "from datetime import UTC, datetime\nfrom email.utils import parsedate_to_datetime\n",
            ),
            _lines(
                re.escape(
                    "delay = parse_retry_after(retry_after, self._clock()) if retry_after else None"
                ),
                block,
                1,
            ),
        )


# --- tasks --------------------------------------------------------------------------


def _task(
    *,
    id: str,
    family: str,
    target_path: str,
    helper: str,
    helper_path: str,
    instruction: str,
    primitives: tuple[str, ...],
    test_cases: tuple[FunctionalCase, ...],
    reused_source: str,
    duplicated_source: str,
) -> CodingTask:
    files = SNAPSHOTS[family]["files"]
    return CodingTask(
        id=id,
        family=family,  # type: ignore[arg-type]
        instruction=f"In {target_path}, add {instruction}",
        helper=helper,
        primitives=primitives,
        helper_source=_helper_source(helper_path, files[helper_path], helper),
        target_path=target_path,
        helper_module=_module(helper_path),
        test_cases=test_cases,
        reused_source=_source(reused_source),
        duplicated_source=_source(duplicated_source),
    )


_VLLM_PATH = "src/jig/llm/vllm.py"
_RUBRIC_PATH = "src/jig/feedback/rubric_judge.py"
_JSONL_PATH = "src/jig/tracing/jsonl.py"
_MASTODON_PATH = "src/scout/platforms/mastodon.py"
_TARGETS = {
    _VLLM_PATH: _VLLM,
    _RUBRIC_PATH: _RUBRIC_JUDGE,
    _JSONL_PATH: _JSONL_TRACER,
    _MASTODON_PATH: _MASTODON,
}


def _parse_error(provider: str = "vllm") -> dict[str, Any]:
    return {"error": {"type": "JigLLMError", "provider": provider, "retryable": True}}


def _wrapped(message: str, status_code: int | None) -> dict[str, Any]:
    return {
        "type": "JigLLMError",
        "message": message,
        "provider": "vllm",
        "status_code": status_code,
        "retryable": False,
    }


_MESSAGES = [{"role": "user", "content": "Summarize the release notes."}]
_SCHEMA_FORMAT = {
    "type": "json_schema",
    "json_schema": {"name": "notes", "schema": {"type": "object"}},
}

_FIXTURES: tuple[tuple[CodingTask, Callable[[dict[str, str]], None]], ...] = (
    (
        _task(
            id="tool-args",
            family="jig-llm",
            target_path=_VLLM_PATH,
            helper="parse_tool_arguments",
            helper_path="src/jig/llm/_parsing.py",
            instruction=(
                "implement(payload), which converts one tool call from a vLLM response. "
                'payload is {"id", "name", "arguments"}, where arguments may be an object, a '
                'JSON string, an empty string or null. Return {"id", "name", "arguments"} with '
                "arguments as an object ({} when empty or null). If the arguments string is not "
                'valid JSON or does not decode to an object, return {"error": {"type", '
                '"provider", "retryable"}} describing the retryable JigLLMError this adapter '
                'raises for it, with provider "vllm".'
            ),
            primitives=("json.loads",),
            test_cases=_cases(
                (
                    {"id": "c1", "name": "search", "arguments": '{"query": "jig", "limit": 3}'},
                    {"id": "c1", "name": "search", "arguments": {"query": "jig", "limit": 3}},
                ),
                (
                    {"id": "c2", "name": "clock", "arguments": ""},
                    {"id": "c2", "name": "clock", "arguments": {}},
                ),
                ({"id": "c3", "name": "search", "arguments": '{"query": '}, _parse_error()),
                ({"id": "c4", "name": "search", "arguments": '["jig"]'}, _parse_error()),
            ),
            reused_source="""
                from jig.llm._parsing import parse_tool_arguments


                def implement(payload):
                    try:
                        arguments = parse_tool_arguments(payload["arguments"], "vllm")
                    except JigLLMError as error:
                        return {
                            "error": {
                                "type": type(error).__name__,
                                "provider": error.provider,
                                "retryable": error.retryable,
                            }
                        }
                    return {"id": payload["id"], "name": payload["name"], "arguments": arguments}
            """,
            duplicated_source="""
                import json


                def implement(payload):
                    arguments = payload["arguments"] or {}
                    if isinstance(arguments, str):
                        try:
                            arguments = json.loads(arguments)
                        except json.JSONDecodeError:
                            arguments = None
                    if not isinstance(arguments, dict):
                        return {"error": {"type": "JigLLMError", "provider": "vllm", "retryable": True}}
                    return {"id": payload["id"], "name": payload["name"], "arguments": arguments}
            """,
        ),
        _inline_tool_arguments,
    ),
    (
        _task(
            id="llm-error",
            family="jig-llm",
            target_path=_VLLM_PATH,
            helper="wrap_llm_error",
            helper_path="src/jig/llm/_common.py",
            instruction=(
                "implement(payload), which converts a failed vLLM request into the error this "
                "adapter raises. vLLM is called through the OpenAI SDK, whose exceptions carry "
                "the HTTP status in a status_code attribute (absent for connection failures). "
                'Build such an exception from payload["message"] and payload["status_code"] '
                "(set the attribute only when it is not null), convert it into the JigLLMError "
                'this adapter raises, with provider "vllm", and return {"type", "message", '
                '"provider", "status_code", "retryable"} for that error.'
            ),
            primitives=("JigLLMError",),
            test_cases=_cases(
                (
                    {"message": "Rate limit exceeded", "status_code": 429},
                    _wrapped("Rate limit exceeded", 429),
                ),
                (
                    {"message": "Model not found", "status_code": 404},
                    _wrapped("Model not found", 404),
                ),
                (
                    {"message": "Internal server error", "status_code": 500},
                    _wrapped("Internal server error", 500),
                ),
                (
                    {"message": "Connection refused", "status_code": None},
                    _wrapped("Connection refused", None),
                ),
            ),
            reused_source="""
                from jig.llm._common import wrap_llm_error


                def implement(payload):
                    class APIError(Exception):
                        pass

                    error = APIError(payload["message"])
                    if payload["status_code"] is not None:
                        error.status_code = payload["status_code"]
                    wrapped = wrap_llm_error(error, "vllm")
                    return {
                        "type": type(wrapped).__name__,
                        "message": str(wrapped),
                        "provider": wrapped.provider,
                        "status_code": wrapped.status_code,
                        "retryable": wrapped.retryable,
                    }
            """,
            duplicated_source="""
                def implement(payload):
                    class APIError(Exception):
                        pass

                    error = APIError(payload["message"])
                    if payload["status_code"] is not None:
                        error.status_code = payload["status_code"]
                    wrapped = JigLLMError(str(error), "vllm", status_code=getattr(error, "status_code", None))
                    return {
                        "type": type(wrapped).__name__,
                        "message": str(wrapped),
                        "provider": wrapped.provider,
                        "status_code": wrapped.status_code,
                        "retryable": wrapped.retryable,
                    }
            """,
        ),
        _inline_error_wrapping,
    ),
    (
        _task(
            id="request-kwargs",
            family="jig-llm",
            target_path=_VLLM_PATH,
            helper="merge_completion_kwargs",
            helper_path="src/jig/llm/_common.py",
            instruction=(
                "implement(payload), which builds the keyword arguments for a vLLM "
                'chat-completions request. payload has "model" and "messages" (a list of '
                '{"role", "content"}) and may have "temperature", "max_tokens", "response_format", '
                '"provider_params" and "reasoning". Return {"model", "messages"} as given plus '
                "temperature, max_tokens and response_format when they are not null, then every "
                "provider_params entry, which wins over the values before it. vLLM has no "
                "reasoning switch: when reasoning is not null, return "
                '{"error": "UnsupportedReasoningError"} instead.'
            ),
            primitives=("update", "UnsupportedReasoningError", "UnsupportedResponseFormatError"),
            test_cases=_cases(
                (
                    {
                        "model": "qwen3-32b",
                        "messages": _MESSAGES,
                        "temperature": 0.2,
                        "max_tokens": 256,
                    },
                    {
                        "model": "qwen3-32b",
                        "messages": _MESSAGES,
                        "temperature": 0.2,
                        "max_tokens": 256,
                    },
                ),
                (
                    {
                        "model": "qwen3-32b",
                        "messages": _MESSAGES,
                        "temperature": 0.2,
                        "provider_params": {"temperature": 0.9, "top_k": 20},
                    },
                    {"model": "qwen3-32b", "messages": _MESSAGES, "temperature": 0.9, "top_k": 20},
                ),
                (
                    {
                        "model": "qwen3-32b",
                        "messages": _MESSAGES,
                        "temperature": 0,
                        "response_format": _SCHEMA_FORMAT,
                    },
                    {
                        "model": "qwen3-32b",
                        "messages": _MESSAGES,
                        "temperature": 0,
                        "response_format": _SCHEMA_FORMAT,
                    },
                ),
                (
                    {"model": "qwen3-32b", "messages": _MESSAGES, "reasoning": False},
                    {"error": "UnsupportedReasoningError"},
                ),
            ),
            reused_source="""
                from jig.llm._common import merge_completion_kwargs


                def implement(payload):
                    params = CompletionParams(
                        messages=[
                            Message(role=Role(message["role"]), content=message["content"])
                            for message in payload["messages"]
                        ],
                        temperature=payload.get("temperature"),
                        max_tokens=payload.get("max_tokens"),
                        provider_params=payload.get("provider_params"),
                        response_format=payload.get("response_format"),
                        reasoning=payload.get("reasoning"),
                    )
                    kwargs = {"model": payload["model"], "messages": payload["messages"]}
                    try:
                        merge_completion_kwargs(kwargs, params, supports_response_format=True)
                    except UnsupportedReasoningError as error:
                        return {"error": type(error).__name__}
                    return kwargs
            """,
            duplicated_source="""
                def implement(payload):
                    if payload.get("reasoning") is not None:
                        return {"error": "UnsupportedReasoningError"}
                    kwargs = {"model": payload["model"], "messages": payload["messages"]}
                    for key in ("temperature", "max_tokens", "response_format"):
                        if payload.get(key) is not None:
                            kwargs[key] = payload[key]
                    kwargs.update(payload.get("provider_params") or {})
                    return kwargs
            """,
        ),
        _inline_completion_kwargs,
    ),
    (
        _task(
            id="usage-cost",
            family="jig-llm",
            target_path=_VLLM_PATH,
            helper="stamp_cost",
            helper_path="src/jig/llm/pricing.py",
            instruction=(
                "implement(payload), which fills in the cost of a vLLM completion. payload has "
                '"model", "input_tokens", "output_tokens" and "cost" (null when vLLM did not '
                'report one). Return {"input_tokens", "output_tokens", "cost"}: keep a reported '
                "cost, otherwise price the tokens in USD from jig's per-model pricing table, "
                "leaving cost null for a model the table does not price."
            ),
            primitives=("compute_cost", "get_pricing"),
            test_cases=_cases(
                (
                    {
                        "model": "gpt-4o-mini-2024-07-18",
                        "input_tokens": 1_000_000,
                        "output_tokens": 1_000_000,
                        "cost": None,
                    },
                    {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cost": 0.75},
                ),
                (
                    {
                        "model": "claude-haiku-4-5",
                        "input_tokens": 2_000_000,
                        "output_tokens": 0,
                        "cost": None,
                    },
                    {"input_tokens": 2_000_000, "output_tokens": 0, "cost": 2.0},
                ),
                (
                    {
                        "model": "qwen3-32b",
                        "input_tokens": 1200,
                        "output_tokens": 300,
                        "cost": None,
                    },
                    {"input_tokens": 1200, "output_tokens": 300, "cost": None},
                ),
                (
                    {"model": "gpt-4o", "input_tokens": 1200, "output_tokens": 300, "cost": 0.02},
                    {"input_tokens": 1200, "output_tokens": 300, "cost": 0.02},
                ),
            ),
            reused_source="""
                from jig.llm.pricing import stamp_cost


                def implement(payload):
                    usage = Usage(
                        input_tokens=payload["input_tokens"],
                        output_tokens=payload["output_tokens"],
                        cost=payload["cost"],
                    )
                    stamp_cost(usage, payload["model"])
                    return {
                        "input_tokens": usage.input_tokens,
                        "output_tokens": usage.output_tokens,
                        "cost": usage.cost,
                    }
            """,
            duplicated_source="""
                from jig.llm.pricing import compute_cost


                def implement(payload):
                    cost = payload["cost"]
                    if cost is None:
                        cost = compute_cost(payload["model"], payload["input_tokens"], payload["output_tokens"])
                    return {
                        "input_tokens": payload["input_tokens"],
                        "output_tokens": payload["output_tokens"],
                        "cost": cost,
                    }
            """,
        ),
        _inline_cost_stamping,
    ),
    (
        _task(
            id="judge-reply",
            family="jig-feedback",
            target_path=_RUBRIC_PATH,
            helper="strip_markdown_fence",
            helper_path="src/jig/feedback/parsing.py",
            instruction=(
                'implement(payload), which parses a rubric judge\'s reply. payload["content"] '
                "is the judge model's response text: one JSON object, which models often wrap in "
                "a markdown code fence (``` or ```json) around the whole reply. Return the parsed "
                'object, or {"error": "GradeParseError"} when the reply is not a JSON object. A '
                "fenced block with prose around it is not unwrapped."
            ),
            primitives=(
                "match",
                "fullmatch",
                "search",
                "sub",
                "removeprefix",
                "removesuffix",
                "startswith",
                "endswith",
                "split",
                "splitlines",
            ),
            test_cases=_cases(
                ({"content": '{"clarity": 0.8}'}, {"clarity": 0.8}),
                (
                    {"content": '```json\n{"clarity": 0.8, "accuracy": 0.5}\n```'},
                    {"clarity": 0.8, "accuracy": 0.5},
                ),
                ({"content": '\n```\n{"accuracy": 1.0}\n```\n'}, {"accuracy": 1.0}),
                (
                    {"content": 'Here are the scores:\n```json\n{"clarity": 0.8}\n```'},
                    {"error": "GradeParseError"},
                ),
            ),
            reused_source="""
                from jig.feedback.parsing import strip_markdown_fence


                def implement(payload):
                    try:
                        data = json.loads(strip_markdown_fence(payload["content"]))
                    except json.JSONDecodeError:
                        return {"error": "GradeParseError"}
                    if not isinstance(data, dict):
                        return {"error": "GradeParseError"}
                    return data
            """,
            duplicated_source="""
                def implement(payload):
                    text = payload["content"].strip()
                    if text.startswith("```") and text.endswith("```"):
                        text = text.split("\\n", 1)[1].rsplit("```", 1)[0]
                    try:
                        data = json.loads(text)
                    except json.JSONDecodeError:
                        return {"error": "GradeParseError"}
                    if not isinstance(data, dict):
                        return {"error": "GradeParseError"}
                    return data
            """,
        ),
        _inline_fence_stripping,
    ),
    (
        _task(
            id="judge-scores",
            family="jig-feedback",
            target_path=_RUBRIC_PATH,
            helper="validate_scores",
            helper_path="src/jig/feedback/validation.py",
            instruction=(
                "implement(payload), which checks the scores a rubric judge returned before "
                'they are recorded. payload["scores"] is a list of {"dimension", "value"}. '
                'Return {"valid": true} when they can be safely persisted and {"valid": false} '
                "otherwise: the list must be non-empty, every dimension a non-empty string, and "
                "every value a finite number from 0 to 1 inclusive."
            ),
            primitives=("isnan", "isinf", "isfinite", "float"),
            test_cases=_cases(
                (
                    {
                        "scores": [
                            {"dimension": "clarity", "value": 0.8},
                            {"dimension": "accuracy", "value": 1},
                        ]
                    },
                    {"valid": True},
                ),
                ({"scores": []}, {"valid": False}),
                ({"scores": [{"dimension": "clarity", "value": 1.5}]}, {"valid": False}),
                ({"scores": [{"dimension": "", "value": 0.5}]}, {"valid": False}),
            ),
            reused_source="""
                from jig.feedback.validation import validate_scores


                def implement(payload):
                    scores = [
                        Score(dimension=item["dimension"], value=item["value"], source=ScoreSource.LLM_JUDGE)
                        for item in payload["scores"]
                    ]
                    try:
                        validate_scores(scores)
                    except ValueError:
                        return {"valid": False}
                    return {"valid": True}
            """,
            duplicated_source="""
                import math


                def implement(payload):
                    if not payload["scores"]:
                        return {"valid": False}
                    for item in payload["scores"]:
                        value = float(item["value"])
                        if not item["dimension"] or not math.isfinite(value) or not 0.0 <= value <= 1.0:
                            return {"valid": False}
                    return {"valid": True}
            """,
        ),
        _inline_score_validation,
    ),
    (
        _task(
            id="span-time",
            family="jig-feedback",
            target_path=_JSONL_PATH,
            helper="parse_aware_utc",
            helper_path="src/jig/_sqlite.py",
            instruction=(
                "implement(payload), which reads back a span start time stored in a JSON Lines "
                'trace file. payload["started_at"] is an ISO timestamp; files written by older '
                "releases hold naive timestamps, which are UTC. Return the time converted to UTC, "
                "in ISO format."
            ),
            primitives=("fromisoformat", "astimezone", "strptime"),
            test_cases=_cases(
                ({"started_at": "2026-09-30T12:00:00+00:00"}, "2026-09-30T12:00:00+00:00"),
                ({"started_at": "2026-09-30T14:30:00+02:00"}, "2026-09-30T12:30:00+00:00"),
                ({"started_at": "2026-09-30T12:00:00"}, "2026-09-30T12:00:00+00:00"),
                (
                    {"started_at": "2026-09-30T12:00:00.250000-04:00"},
                    "2026-09-30T16:00:00.250000+00:00",
                ),
            ),
            reused_source="""
                from jig._sqlite import parse_aware_utc


                def implement(payload):
                    return parse_aware_utc(payload["started_at"]).isoformat()
            """,
            duplicated_source="""
                from datetime import UTC, datetime


                def implement(payload):
                    started = datetime.fromisoformat(payload["started_at"])
                    if started.tzinfo is None:
                        started = started.replace(tzinfo=UTC)
                    return started.astimezone(UTC).isoformat()
            """,
        ),
        _inline_utc_parsing,
    ),
    (
        _task(
            id="source-key",
            family="scout-platforms",
            target_path=_MASTODON_PATH,
            helper="derive_source_key",
            helper_path="src/scout/platforms/base.py",
            instruction=(
                "implement(payload), which returns the checkpoint key for a Mastodon source. "
                'payload has "source_kind" (such as "hashtag" or "account") and "provider_key" '
                "(the hashtag or account id as configured). The key is "
                '"mastodon:<source_kind>:<provider_key>" with each part stripped of surrounding '
                "whitespace and case-folded, so equivalent sources share one checkpoint."
            ),
            primitives=("casefold", "lower", "strip"),
            test_cases=_cases(
                ({"source_kind": "hashtag", "provider_key": " #Rust "}, "mastodon:hashtag:#rust"),
                ({"source_kind": "account", "provider_key": "109302"}, "mastodon:account:109302"),
                ({"source_kind": " Hashtag", "provider_key": "ÉCOLE"}, "mastodon:hashtag:école"),
                ({"source_kind": "hashtag", "provider_key": "Straße"}, "mastodon:hashtag:strasse"),
            ),
            reused_source="""
                from scout.platforms.base import derive_source_key


                def implement(payload):
                    descriptor = SourceDescriptor("mastodon", payload["source_kind"], payload["provider_key"])
                    return derive_source_key(descriptor)
            """,
            duplicated_source="""
                def implement(payload):
                    parts = ("mastodon", payload["source_kind"], payload["provider_key"])
                    return ":".join(part.strip().casefold() for part in parts)
            """,
        ),
        _inline_source_keys,
    ),
    (
        _task(
            id="source-boundary",
            family="scout-platforms",
            target_path=_MASTODON_PATH,
            helper="source_since",
            helper_path="src/scout/platforms/base.py",
            instruction=(
                "implement(payload), which resolves where fetching a Mastodon source starts. "
                'payload has "source_kind", "provider_key", "fallback" (an ISO time or null) and '
                '"checkpoints" (null, or an object mapping source keys to ISO times or null). '
                "Recovery probes pass no checkpoints and use fallback. Otherwise use this source's "
                "own checkpoint, found by its source key; a source without one starts cold (null) "
                "rather than from fallback. Return the boundary as an ISO time or null."
            ),
            primitives=("derive_source_key", "casefold"),
            test_cases=_cases(
                (
                    {
                        "source_kind": "hashtag",
                        "provider_key": "rust",
                        "fallback": "2026-09-01T00:00:00+00:00",
                        "checkpoints": None,
                    },
                    "2026-09-01T00:00:00+00:00",
                ),
                (
                    {
                        "source_kind": "hashtag",
                        "provider_key": " #Rust ",
                        "fallback": "2026-09-01T00:00:00+00:00",
                        "checkpoints": {"mastodon:hashtag:#rust": "2026-09-29T08:00:00+00:00"},
                    },
                    "2026-09-29T08:00:00+00:00",
                ),
                (
                    {
                        "source_kind": "account",
                        "provider_key": "109302",
                        "fallback": "2026-09-01T00:00:00+00:00",
                        "checkpoints": {"mastodon:hashtag:#rust": "2026-09-29T08:00:00+00:00"},
                    },
                    None,
                ),
                (
                    {
                        "source_kind": "hashtag",
                        "provider_key": "#rust",
                        "fallback": None,
                        "checkpoints": {"mastodon:hashtag:#rust": None},
                    },
                    None,
                ),
            ),
            reused_source="""
                from scout.platforms.base import source_since


                def implement(payload):
                    def parse(value):
                        return datetime.fromisoformat(value) if value is not None else None

                    descriptor = SourceDescriptor("mastodon", payload["source_kind"], payload["provider_key"])
                    checkpoints = payload["checkpoints"]
                    if checkpoints is not None:
                        checkpoints = {key: parse(value) for key, value in checkpoints.items()}
                    boundary = source_since(descriptor, parse(payload["fallback"]), checkpoints)
                    return boundary.isoformat() if boundary is not None else None
            """,
            duplicated_source="""
                from scout.platforms.base import derive_source_key


                def implement(payload):
                    if payload["checkpoints"] is None:
                        return payload["fallback"]
                    descriptor = SourceDescriptor("mastodon", payload["source_kind"], payload["provider_key"])
                    return payload["checkpoints"].get(derive_source_key(descriptor))
            """,
        ),
        _inline_source_boundaries,
    ),
    (
        _task(
            id="status-time",
            family="scout-platforms",
            target_path=_MASTODON_PATH,
            helper="parse_platform_ts",
            helper_path="src/scout/platforms/base.py",
            instruction=(
                "implement(payload), which parses a Mastodon status timestamp. "
                'payload["created_at"] is the status\'s ISO 8601 created_at, possibly ending in '
                "Z. Return it as a timezone-aware time in ISO format, keeping its offset, or null "
                "when it is empty, malformed or has no timezone; never substitute the current time."
            ),
            primitives=("fromisoformat", "strptime"),
            test_cases=_cases(
                ({"created_at": "2026-09-30T12:00:00.000Z"}, "2026-09-30T12:00:00+00:00"),
                ({"created_at": "2026-09-30T14:00:00+02:00"}, "2026-09-30T14:00:00+02:00"),
                ({"created_at": "2026-09-30T12:00:00"}, None),
                ({"created_at": "yesterday"}, None),
            ),
            reused_source="""
                from scout.platforms.base import parse_platform_ts


                def implement(payload):
                    parsed = parse_platform_ts(payload["created_at"])
                    return parsed.isoformat() if parsed is not None else None
            """,
            duplicated_source="""
                def implement(payload):
                    text = payload["created_at"]
                    if text.endswith("Z"):
                        text = text[:-1] + "+00:00"
                    try:
                        parsed = datetime.fromisoformat(text)
                    except ValueError:
                        return None
                    return parsed.isoformat() if parsed.tzinfo is not None else None
            """,
        ),
        _inline_timestamp_parsing,
    ),
    (
        _task(
            id="retry-delay",
            family="scout-platforms",
            target_path=_MASTODON_PATH,
            helper="parse_retry_after",
            helper_path="src/scout/platforms/base.py",
            instruction=(
                "implement(payload), which works out how long to wait before retrying a "
                'rate-limited Mastodon request. payload has "retry_after", the Retry-After header '
                'value (delay-seconds or an HTTP-date; a date without a zone is UTC), and "now", '
                "an ISO time. Return the delay in seconds as a number, or null when the value is "
                "empty, unparseable or already in the past."
            ),
            primitives=("parsedate_to_datetime", "float", "strptime"),
            test_cases=_cases(
                ({"retry_after": "30", "now": "2026-09-30T12:00:00+00:00"}, 30.0),
                (
                    {
                        "retry_after": "Wed, 30 Sep 2026 12:01:00 GMT",
                        "now": "2026-09-30T12:00:00+00:00",
                    },
                    60.0,
                ),
                ({"retry_after": "-5", "now": "2026-09-30T12:00:00+00:00"}, None),
                ({"retry_after": "soon", "now": "2026-09-30T12:00:00+00:00"}, None),
            ),
            reused_source="""
                from scout.platforms.base import parse_retry_after


                def implement(payload):
                    return parse_retry_after(payload["retry_after"], datetime.fromisoformat(payload["now"]))
            """,
            duplicated_source="""
                from email.utils import parsedate_to_datetime


                def implement(payload):
                    value = payload["retry_after"].strip()
                    try:
                        delay = float(value)
                    except ValueError:
                        try:
                            when = parsedate_to_datetime(value)
                        except (TypeError, ValueError, IndexError):
                            return None
                        if when.tzinfo is None:
                            when = when.replace(tzinfo=UTC)
                        delay = (when - datetime.fromisoformat(payload["now"])).total_seconds()
                    return delay if delay >= 0 else None
            """,
        ),
        _inline_retry_after,
    ),
)

CODEBASE_TASKS: tuple[CodingTask, ...] = tuple(task for task, _ in _FIXTURES)


def _with_packages(files: dict[str, str]) -> dict[str, str]:
    """Add an empty __init__.py to every package directory that lacks one."""
    packages = {
        "/".join(parts[:index]) + "/__init__.py"
        for path in files
        for parts in [PurePosixPath(path).parts]
        for index in range(2 if parts[0] == "src" else 1, len(parts))
    }
    return {**dict.fromkeys(packages, ""), **files}


# --- neighbours -----------------------------------------------------------------------
#
# For the ``near`` variants, the target module already holds one function that
# needs the helper's behaviour too. In the clean arm it calls the helper; in
# the inconsistent arm it inlines the logic, in the style of the distant
# callers' inlined copies, and the module imports whatever that copy needs.


class _Neighbour:
    def __init__(self, clean: str, inline: str, imports: str = "", clean_imports: str = "") -> None:
        self.clean = _source(clean)
        self.inline = _source(inline)
        self.imports = imports
        self.clean_imports = clean_imports


_NEIGHBOURS = {
    "tool-args": _Neighbour(
        '''
        def _finish_streamed_tool_calls(pending: dict[int, dict[str, str]]) -> list[ToolCall]:
            """Assemble tool calls whose argument JSON arrived in stream fragments."""
            calls = []
            for index in sorted(pending):
                entry = pending[index]
                calls.append(
                    ToolCall(
                        id=entry["id"],
                        name=entry["name"],
                        arguments=parse_tool_arguments(entry["arguments"], "vllm"),
                    )
                )
            return calls
        ''',
        '''
        def _finish_streamed_tool_calls(pending: dict[int, dict[str, str]]) -> list[ToolCall]:
            """Assemble tool calls whose argument JSON arrived in stream fragments."""
            calls = []
            for index in sorted(pending):
                entry = pending[index]
                calls.append(
                    ToolCall(
                        id=entry["id"],
                        name=entry["name"],
                        arguments=json.loads(entry["arguments"] or "{}"),
                    )
                )
            return calls
        ''',
        "import json\n",
    ),
    "llm-error": _Neighbour(
        '''
        async def _served_models(client: Any) -> list[str]:
            """Ids of the models this vLLM server has loaded."""
            try:
                page = await client.models.list()
            except Exception as e:
                raise wrap_llm_error(e, "vllm") from e
            return [model.id for model in page.data]
        ''',
        '''
        async def _served_models(client: Any) -> list[str]:
            """Ids of the models this vLLM server has loaded."""
            try:
                page = await client.models.list()
            except Exception as e:
                raise JigLLMError(str(e), "vllm", status_code=getattr(e, "status_code", None)) from e
            return [model.id for model in page.data]
        ''',
    ),
    "request-kwargs": _Neighbour(
        '''
        def _stream_kwargs(
            model: str, messages: list[dict[str, Any]], params: CompletionParams
        ) -> dict[str, Any]:
            """Keyword arguments for a streamed chat completion that reports usage."""
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "stream": True,
                "stream_options": {"include_usage": True},
            }
            merge_completion_kwargs(kwargs, params, supports_response_format=True)
            return kwargs
        ''',
        _source(
            '''
            def _stream_kwargs(
                model: str, messages: list[dict[str, Any]], params: CompletionParams
            ) -> dict[str, Any]:
                """Keyword arguments for a streamed chat completion that reports usage."""
                kwargs: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "stream": True,
                    "stream_options": {"include_usage": True},
                }
            '''
        )
        + indent(
            _merge_block(
                "kwargs",
                response_format='kwargs["response_format"] = params.response_format',
                reasoning="params.reasoning is not None",
            ),
            "    ",
        )
        + "    return kwargs\n",
    ),
    "usage-cost": _Neighbour(
        '''
        def _usage(raw: Any, model: str) -> Usage:
            """Token usage from an OpenAI-shaped usage block, priced when vLLM reports no cost."""
            usage = Usage(input_tokens=raw.prompt_tokens, output_tokens=raw.completion_tokens)
            return stamp_cost(usage, model)
        ''',
        '''
        def _usage(raw: Any, model: str) -> Usage:
            """Token usage from an OpenAI-shaped usage block, priced when vLLM reports no cost."""
            usage = Usage(input_tokens=raw.prompt_tokens, output_tokens=raw.completion_tokens)
            if usage.cost is None:
                usage.cost = compute_cost(model, usage.input_tokens, usage.output_tokens)
            return usage
        ''',
        "from jig.llm.pricing import compute_cost\n",
    ),
    "judge-reply": _Neighbour(
        '''
        def _rationale(content: str) -> str:
            """The judge's free-text rationale, from the optional "feedback" field of its reply."""
            data = json.loads(strip_markdown_fence(content))
            return str(data.get("feedback", ""))
        ''',
        '''
        def _rationale(content: str) -> str:
            """The judge's free-text rationale, from the optional "feedback" field of its reply."""
            text = content.strip()
            if text.startswith("```"):
                text = text.split("\\n", 1)[-1].rsplit("```", 1)[0]
            data = json.loads(text)
            return str(data.get("feedback", ""))
        ''',
    ),
    "judge-scores": _Neighbour(
        '''
        def _criterion_scores(data: dict[str, Any], criteria: list[str]) -> list[Score]:
            """One Score per rubric criterion, checked before the grade is returned."""
            scores = [
                Score(dimension=name, value=float(data[name]), source=ScoreSource.LLM_JUDGE)
                for name in criteria
            ]
            validate_scores(scores)
            return scores
        ''',
        '''
        def _criterion_scores(data: dict[str, Any], criteria: list[str]) -> list[Score]:
            """One Score per rubric criterion, checked before the grade is returned."""
            scores = [
                Score(dimension=name, value=float(data[name]), source=ScoreSource.LLM_JUDGE)
                for name in criteria
            ]
            if not scores:
                raise ValueError("scores must be non-empty")
            for s in scores:
                if not s.dimension or not 0.0 <= float(s.value) <= 1.0:
                    raise ValueError(f"invalid score {s.value!r} for dimension {s.dimension!r}")
            return scores
        ''',
    ),
    "span-time": _Neighbour(
        '''
        def _ended_at(record: dict[str, Any]) -> datetime | None:
            """A span's end time as written to the trace file, or None for an open span."""
            raw = record.get("ended_at")
            if raw is None:
                return None
            return parse_aware_utc(raw)
        ''',
        '''
        def _ended_at(record: dict[str, Any]) -> datetime | None:
            """A span's end time as written to the trace file, or None for an open span."""
            raw = record.get("ended_at")
            if raw is None:
                return None
            return datetime.fromisoformat(raw).astimezone(UTC)
        ''',
        "from datetime import UTC, datetime\n",
        "from datetime import datetime\n",
    ),
    "source-key": _Neighbour(
        '''
        def _unique_sources(descriptors: Sequence[SourceDescriptor]) -> list[SourceDescriptor]:
            """Drop configured sources that share a checkpoint with an earlier one."""
            seen: set[str] = set()
            unique = []
            for descriptor in descriptors:
                key = derive_source_key(descriptor)
                if key not in seen:
                    seen.add(key)
                    unique.append(descriptor)
            return unique
        ''',
        '''
        def _unique_sources(descriptors: Sequence[SourceDescriptor]) -> list[SourceDescriptor]:
            """Drop configured sources that share a checkpoint with an earlier one."""
            seen: set[str] = set()
            unique = []
            for descriptor in descriptors:
                key = f"{descriptor.platform.strip().casefold()}:{descriptor.source_kind.strip().casefold()}:{descriptor.provider_key.strip().casefold()}"
                if key not in seen:
                    seen.add(key)
                    unique.append(descriptor)
            return unique
        ''',
    ),
    "source-boundary": _Neighbour(
        '''
        def _hashtag_boundaries(
            descriptors: Sequence[SourceDescriptor],
            since: datetime | None,
            source_checkpoints: Mapping[str, datetime | None] | None,
        ) -> dict[str, datetime | None]:
            """Where each configured hashtag timeline resumes, by hashtag."""
            return {
                descriptor.provider_key: source_since(descriptor, since, source_checkpoints)
                for descriptor in descriptors
            }
        ''',
        '''
        def _hashtag_boundaries(
            descriptors: Sequence[SourceDescriptor],
            since: datetime | None,
            source_checkpoints: Mapping[str, datetime | None] | None,
        ) -> dict[str, datetime | None]:
            """Where each configured hashtag timeline resumes, by hashtag."""
            return {
                descriptor.provider_key: (
                    since if source_checkpoints is None
                    else source_checkpoints.get(derive_source_key(descriptor))
                )
                for descriptor in descriptors
            }
        ''',
        "from scout.platforms.base import derive_source_key\n",
    ),
    "status-time": _Neighbour(
        '''
        def _edited_at(status: Mapping[str, object]) -> datetime | None:
            """When a status was last edited, or None for a status never edited."""
            raw = status.get("edited_at")
            if not raw:
                return None
            return parse_platform_ts(str(raw))
        ''',
        '''
        def _edited_at(status: Mapping[str, object]) -> datetime | None:
            """When a status was last edited, or None for a status never edited."""
            raw = status.get("edited_at")
            if not raw:
                return None
            try:
                dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            except ValueError:
                return None
            return dt if dt.tzinfo is not None else None
        ''',
    ),
    "retry-delay": _Neighbour(
        '''
        def _backoff(response: httpx.Response, now: datetime) -> float | None:
            """Seconds to wait before retrying a rate-limited response, or None to give up."""
            retry_after = response.headers.get("Retry-After")
            return parse_retry_after(retry_after, now) if retry_after else None
        ''',
        '''
        def _backoff(response: httpx.Response, now: datetime) -> float | None:
            """Seconds to wait before retrying a rate-limited response, or None to give up."""
            retry_after = response.headers.get("Retry-After")
            delay = None
            if retry_after:
                try:
                    delay = float(retry_after)
                except ValueError:
                    delay = (parsedate_to_datetime(retry_after) - now).total_seconds()
            return delay
        ''',
        "from email.utils import parsedate_to_datetime\n",
    ),
}


def _target_stub(task: CodingTask, *, imports: str = "", neighbour: str = "") -> str:
    """The target module, already importing the helper as a neighbouring module would."""
    stub = _TARGETS[task.target_path]
    nodes = [node for node in ast.parse(stub).body if isinstance(node, ast.Import | ast.ImportFrom)]

    def end(node: ast.stmt) -> int:
        return node.end_lineno or node.lineno

    def standard(line: str) -> bool:
        return line.split()[1].split(".")[0] in sys.stdlib_module_names

    # Standard-library imports join that group; the rest follow the last import.
    extra = imports.splitlines(keepends=True)
    last_standard = max(
        end(node)
        for node in nodes
        if (node.names[0].name if isinstance(node, ast.Import) else node.module or "").split(".")[0]
        in sys.stdlib_module_names
    )
    lines = stub.splitlines(keepends=True)
    lines.insert(
        max(map(end, nodes)),
        "".join(line for line in extra if not standard(line))
        + f"from {task.helper_module} import {task.helper}\n",
    )
    lines.insert(last_standard, "".join(line for line in extra if standard(line)))
    return "".join(lines) + ("\n\n" + neighbour if neighbour else "")


def codebase_repository_variants(*, near: bool = False) -> dict[str, dict[str, dict[str, str]]]:
    """Both arms of every subject; they differ only in how existing code reaches the helper.

    With ``near``, the target module's own neighbour function is part of that
    difference; otherwise the target module is identical in both arms.
    """
    variants: dict[str, dict[str, dict[str, str]]] = {}
    for task, inline in _FIXTURES:
        neighbour = _NEIGHBOURS[task.id] if near else None
        clean = _with_packages(
            {
                **SNAPSHOTS[task.family]["files"],
                task.target_path: _target_stub(task)
                if neighbour is None
                else _target_stub(task, imports=neighbour.clean_imports, neighbour=neighbour.clean),
            }
        )
        inconsistent = dict(clean)
        inline(inconsistent)
        if neighbour is not None:
            inconsistent[task.target_path] = _target_stub(
                task, imports=neighbour.imports, neighbour=neighbour.inline
            )
        variants[task.id] = {"clean": clean, "inconsistent": inconsistent}
    return variants
