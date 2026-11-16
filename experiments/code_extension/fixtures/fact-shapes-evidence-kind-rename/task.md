Rename the existing written-record category to attestation.

Typed service operations must accept attestation.

All existing readers must follow the renamed selection, and the former selection must no longer be accepted.

The primary operation must accept attestation under its normal validation rules.

The independent validation operation must recognize attestation.

The adjacent operation must also accept attestation.

After all database migrations have been applied in order, storing attestation must succeed.

The feature must follow the original stored source throughout its lifecycle, including removal, without keeping a separate copy.

Record labels containing letters, digits, underscores or hyphens must be accepted up to a length of 120 characters, and longer or otherwise malformed labels must be rejected.
