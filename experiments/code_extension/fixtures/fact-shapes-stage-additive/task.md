Add a triaged stage.

Typed service operations must recognize triaged.

The primary operation must accept triaged under its normal validation rules.

The independent validation operation must recognize triaged.

The adjacent operation must also recognize triaged.

After all database migrations have been applied in order, storing triaged must succeed.

Build status for a job in the new stage must follow whether its original session is running, including after that session ends, without retaining a separate copy.

Labels containing letters, digits, underscores or hyphens must be accepted up to a length of 80 characters, and longer or otherwise malformed labels must be rejected.
