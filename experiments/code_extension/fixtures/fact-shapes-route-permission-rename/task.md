Rename the existing read-only case permission to case inspection.

Typed service operations must accept case inspection.

All existing readers must follow the renamed selection, and the former selection must no longer be accepted.

The primary operation must accept case inspection under its normal validation rules.

The independent validation operation must recognize case inspection.

The adjacent operation must also accept case inspection.

After all database migrations have been applied in order, storing case inspection must succeed.

The feature must follow the original stored source throughout its lifecycle, including removal, without keeping a separate copy.

Record labels containing letters, digits, underscores or hyphens must be accepted up to a length of 120 characters, and longer or otherwise malformed labels must be rejected.
