# Import Match + Patch Rules

## Goals

- Keep journal files as the primary source of truth.
- Preserve all user comments, tags, and manual edits.
- Make import idempotent across reruns and parser changes where identity fields remain stable.

## Identity model

For each converted transaction, compute:

- `source_identity`: SHA-256 of stable tuple:
  - institution
  - transaction date
  - normalized payee text
  - institution-side posting amount
- `source_payload_hash`: SHA-256 of normalized transaction body (full emitted txn text)

Importer writes metadata comments on new transactions:

- `; source_identity: ...`
- `; source_payload_hash: ...`
- `; source_file_sha256: ...`
- `; importer_version: mvp2`

## Match states

Given existing imported identities (journal metadata + sqlite index):

- `new`: `source_identity` not found
  - Action: append transaction
- `duplicate`: `source_identity` found and payload hash matches (or existing hash unknown)
  - Action: skip append
- `conflict`: `source_identity` found but payload hash differs
  - Action: skip append and show in conflict list for user review

## Patch semantics

- Import is append-only for `new` transactions.
- No rewrite/normalization pass over existing journal.
- Existing transactions are never auto-modified.
- SQLite index is updated after apply and stores ingestion provenance.

## Why this preserves rich journals

- Manual annotations remain untouched.
- Transaction text already in journal is treated as authoritative content.
- Ingestion DB acts as idempotency/audit memory, not accounting state.
