"""Verification pilot bounds and their prefilled-session qualification note.

This pilot uses its own settings identity. The worst-case session budget assumes
three blocks and at most one use site per block. Each use site has one
``replace_in_file`` call and result and one ``bun test`` summary. Reserve three
later turns with one 32,768-byte tool result per use site on every turn.

The budget counts encoded JSON bytes, with a conservative 6x expansion for
arbitrary text that may need escaping: 16,384 for the system prompt and task;
3 * 32,768 * 6 = 589,824 for the blocks; 3 * 8,192 * 6 = 147,456 for calls;
3 * 32,768 * 6 = 589,824 for their results; 3 * 8,192 * 6 = 147,456 for
test summaries; 3 * 3 * 32,768 * 6 = 1,769,472 for later tool results; and
65,536 for message framing. Total: 3,325,952 bytes. The conversation ceiling
is 3,670,016 bytes (3.5 MiB), leaving 344,064 bytes of margin. The request
ceiling is 3,932,160 bytes (3.75 MiB), another 262,144 bytes for the schema
and request envelope. Both fit the 4,000,000-byte settings envelope.

This is the pilot's prospective qualification record; the pilot runner must
record observed use and report conversation-limit hits as numerator,
denominator, and rate for every arm and model route. More use sites or larger
prefilled components require a new qualification before authorization.

The shared ``CandidateCause`` wire type does not yet contain
``conversation_limit``. The bridge reports these typed loop stops as
``no_submission`` with ``conversation_limit`` in the detail. Pilot reporting
must distinguish that detail from other ``no_submission`` outcomes when
counting cap hits, or use a future wire cause that makes the distinction.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class VerificationPilotSettings(BaseModel):
    """Frozen bounds for one verification-pilot repository-agent attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    max_turns: Literal[20] = 20
    attempts: Literal[1] = 1
    concurrency: Literal[1] = 1
    provider_retries: Literal[0] = 0
    sdk_retries: Literal[0] = 0
    max_tool_schema_bytes: int = Field(default=16_384, ge=1, le=1_000_000)
    max_tool_output_bytes: int = Field(default=32_768, ge=1, le=1_000_000)
    max_conversation_bytes: int = Field(default=3_670_016, ge=1, le=4_000_000)
    max_request_bytes: int = Field(default=3_932_160, ge=1, le=4_000_000)
    max_response_bytes: int = Field(default=131_072, ge=1, le=1_000_000)
    max_output_tokens: int = Field(default=8_192, ge=1, le=32_768)
    max_storage_mb: int = Field(default=512, ge=1, le=4_096)
