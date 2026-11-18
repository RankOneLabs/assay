Rename the existing written-record category to attestation.

Typed service operations must recognize attestation, and new requests must reject the former spelling.

The primary operation must accept attestation under its normal validation rules, and new requests must reject the former spelling.

The independent validation operation must recognize attestation, and new requests must reject the former spelling.

The adjacent operation must also recognize attestation, and new requests must reject the former spelling.

After all database migrations have been applied in order, storing attestation must succeed.

Attachments that omit a category must use the current saved category, and clearing that selection must make such attachments fail without retaining a separate copy, and new requests must reject the former spelling.

Labels containing letters, digits, underscores or hyphens must be accepted up to a length of 80 characters, and longer or otherwise malformed labels must be rejected.
