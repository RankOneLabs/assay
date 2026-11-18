Rename the existing read-only case permission to case inspection.

Typed service operations must recognize case inspect, and new requests must reject the former spelling.

The primary operation must accept case inspect under its normal validation rules, and new requests must reject the former spelling.

The independent validation operation must recognize case inspect, and new requests must reject the former spelling.

The adjacent operation must also recognize case inspect, and new requests must reject the former spelling.

After all database migrations have been applied in order, storing case inspect must succeed.

Grants that omit a permission must use the current saved permission, and clearing that selection must make such grants fail without retaining a separate copy, and new requests must reject the former spelling.

Labels containing letters, digits, underscores or hyphens must be accepted up to a length of 80 characters, and longer or otherwise malformed labels must be rejected.
