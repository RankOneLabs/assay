Add a attestation evidence kind.

Typed service operations must recognize attestation.

The primary operation must accept attestation under its normal validation rules.

The independent validation operation must recognize attestation.

The adjacent operation must also recognize attestation.

After all database migrations have been applied in order, storing attestation must succeed.

Attachments that omit a category must use the current saved category, and clearing that selection must make such attachments fail without retaining a separate copy.

Labels containing letters, digits, underscores or hyphens must be accepted up to a length of 80 characters, and longer or otherwise malformed labels must be rejected.
