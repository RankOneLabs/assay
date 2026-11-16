Add a case inspect route permission.

Typed service operations must recognize case inspect.

The primary operation must accept case inspect under its normal validation rules.

The independent validation operation must recognize case inspect.

The adjacent operation must also recognize case inspect.

After all database migrations have been applied in order, storing case inspect must succeed.

The feature must follow the original stored selection throughout its lifecycle, including removal, without keeping a separate copy.

Labels containing letters, digits, underscores or hyphens must be accepted up to a length of 80 characters, and longer or otherwise malformed labels must be rejected.
