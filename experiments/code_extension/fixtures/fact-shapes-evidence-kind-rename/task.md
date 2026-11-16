Rename the existing written-record category to attestation.

Typed service operations must recognize attestation, and new requests must reject the former spelling.

The primary operation must accept attestation under its normal validation rules, and new requests must reject the former spelling.

The independent validation operation must recognize attestation, and new requests must reject the former spelling.

The adjacent operation must also recognize attestation, and new requests must reject the former spelling.

After all database migrations have been applied in order, storing attestation must succeed, and new requests must reject the former spelling.

The feature must follow the original stored selection throughout its lifecycle, including removal, without keeping a separate copy, and new requests must reject the former spelling.

Labels containing letters, digits, underscores or hyphens must be accepted up to a length of 80 characters, and longer or otherwise malformed labels must be rejected.
