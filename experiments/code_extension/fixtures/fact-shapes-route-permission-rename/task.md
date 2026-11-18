Rename the existing read-only case permission to case inspection.

Everything in the service that accepts the former permission name must accept case inspect instead, stored data included, and new requests must reject the former spelling.

Labels containing letters, digits, underscores or hyphens must be accepted up to a length of 80 characters, and longer or otherwise malformed labels must be rejected.
