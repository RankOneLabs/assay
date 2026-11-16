Rename the initial waiting stage to triaged.

Typed service operations must accept triaged.

All existing readers must follow the renamed selection, and the former selection must no longer be accepted.

The primary operation must accept triaged under its normal validation rules.

The independent validation operation must recognize triaged.

The adjacent operation must also accept triaged.

After all database migrations have been applied in order, storing triaged must succeed.

The feature must follow whether a build is running, including after its session ends, without keeping a separate copy.

Record labels containing letters, digits, underscores or hyphens must be accepted up to a length of 120 characters, and longer or otherwise malformed labels must be rejected.
