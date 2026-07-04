# Ledger Flow Projection Schema Draft

This document drafts a relational schema for Ledger Flow's next backend model.
It keeps plaintext Ledger journals as canonical storage while using SQLite as a
structured projection, operation log, staging store, and coordination layer.

The intent is not to model every legal Ledger construct. The app owns a
documented house-style subset, preserves everything else losslessly where
possible, and records diagnostics when a file is valid Ledger but outside the
managed subset.

## Design Goals

1. Keep plaintext journals canonical.
2. Make the projection rebuildable from journals.
3. Give transactions and postings stable app identities.
4. Preserve user-authored text that the app does not understand.
5. Support transaction-level and posting-level metadata.
6. Represent app operations, stages, and audit metadata in one place.
7. Leave room for local SQLite now and Postgres later.
8. Model reference data (accounts, payees, tags, commodities) as typed
   projections over the `NN-*.dat` directive files.
9. Make the database the durable audit store, replacing `events.jsonl` and
   `imports/import-log.ndjson` without losing their guarantees.

## House Style

Ledger Flow-managed blocks should follow these rules:

- Dates are ISO `YYYY-MM-DD`.
- App-owned metadata keys use the `lf_` prefix.
- Transaction blocks carry one `lf_txn_id`.
- Posting lines carry one `lf_posting_id` comment line when the app needs
  stable posting identity.
- App-authored metadata uses one key/value pair per comment.
- Typed app metadata (dates, amounts, booleans) uses ledger's `::`
  typed-metadata syntax so the value is parsed as a value expression at
  file-read time and validated by ledger itself (`; lf_closed:: [2026-05-31]`).
  String metadata (ids, hashes, account names) keeps the single-colon form —
  a bare string after `::` would be misparsed as an expression.
- Unknown user comments are preserved as raw comments.
- Inline multi-key Ledger metadata is preserved as raw text unless explicitly
  supported later.

Example:

```ledger
2026-05-01 * Grocery Store
    ; lf_txn_id: txn_01J...
    ; lf_source_identity: abc123
    Assets:Checking        USD -10.00
        ; lf_posting_id: post_01J...
        ; statement_payee: My Dear Mom
        ; effective_date:: [2026-05-01]
    Expenses:Groceries
        ; lf_posting_id: post_01K...
```

Directive blocks in `NN-*.dat` files carry app lifecycle metadata the same
way — comment lines inside the block, ignored by the ledger CLI:

```ledger
account Liabilities:Wells Fargo:Credit Card
    note Everyday card
    ; lf_subtype: credit_card
    ; lf_closed:: [2026-05-31]

payee Walmart
    alias WAL-?MART
    ; lf_default_account: Expenses:Groceries
```

## Table Classes

Tables fall into three classes:

- **Projection tables** are rebuildable from plaintext journals.
- **Operation tables** are durable app history and are not fully rebuildable.
- **Workflow tables** are disposable or resumable working state.

Projection tables should be safe to wipe and rebuild. Operation tables should
survive projection rebuilds.

## Core DDL

This is SQLite-flavored DDL. IDs are text so the same schema can migrate to
Postgres without coupling to SQLite rowids. Flags are declared `BOOLEAN`
with `TRUE`/`FALSE` literals — SQLite stores these as `1`/`0` integers
(there is no boolean storage class), but the spelling states intent and is
what Postgres requires.

```sql
CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE journal_files (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL DEFAULT 'journal'
        CHECK (role IN ('journal', 'directives', 'opening', 'archive')),
    content_hash TEXT NOT NULL,
    parsed_at TEXT NOT NULL,
    parse_status TEXT NOT NULL DEFAULT 'ok'
        CHECK (parse_status IN ('ok', 'warning', 'error')),
    last_error TEXT
);

CREATE TABLE transactions (
    id TEXT PRIMARY KEY,
    journal_file_id TEXT NOT NULL REFERENCES journal_files(id) ON DELETE CASCADE,
    txn_order INTEGER NOT NULL,
    date TEXT NOT NULL,
    effective_date TEXT,
    status TEXT NOT NULL DEFAULT 'unmarked'
        CHECK (status IN ('unmarked', 'pending', 'cleared')),
    code TEXT,
    payee TEXT NOT NULL,
    raw_header TEXT NOT NULL,
    raw_block_hash TEXT NOT NULL,
    source_start_line INTEGER NOT NULL,
    source_end_line INTEGER NOT NULL,
    managed_by_app BOOLEAN NOT NULL DEFAULT FALSE,
    parse_status TEXT NOT NULL DEFAULT 'ok'
        CHECK (parse_status IN ('ok', 'preserved_raw', 'warning', 'error')),
    created_from_operation_id TEXT,
    UNIQUE (journal_file_id, txn_order)
);

CREATE INDEX transactions_date_idx ON transactions(date);
CREATE INDEX transactions_payee_idx ON transactions(payee);
CREATE INDEX transactions_file_line_idx ON transactions(journal_file_id, source_start_line);

CREATE TABLE journal_items (
    id TEXT PRIMARY KEY,
    journal_file_id TEXT NOT NULL REFERENCES journal_files(id) ON DELETE CASCADE,
    item_order INTEGER NOT NULL,
    item_type TEXT NOT NULL
        CHECK (item_type IN (
            'blank',
            'comment',
            'include',
            'directive',
            'transaction',
            'raw'
        )),
    transaction_id TEXT REFERENCES transactions(id) ON DELETE SET NULL,
    raw_text TEXT NOT NULL,
    raw_hash TEXT NOT NULL,
    source_start_line INTEGER NOT NULL,
    source_end_line INTEGER NOT NULL,
    parse_status TEXT NOT NULL DEFAULT 'preserved'
        CHECK (parse_status IN ('managed', 'preserved', 'error')),
    UNIQUE (journal_file_id, item_order)
);

CREATE INDEX journal_items_file_order_idx ON journal_items(journal_file_id, item_order);
CREATE INDEX journal_items_transaction_idx ON journal_items(transaction_id);

CREATE TABLE postings (
    id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    posting_order INTEGER NOT NULL,
    account TEXT NOT NULL,
    amount_nano INTEGER,
    commodity TEXT,
    amount_inferred BOOLEAN NOT NULL DEFAULT FALSE,
    balance_assertion_text TEXT,
    raw_line TEXT NOT NULL,
    raw_line_hash TEXT NOT NULL,
    source_line INTEGER NOT NULL,
    managed_by_app BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (transaction_id, posting_order)
);

CREATE INDEX postings_account_idx ON postings(account);
CREATE INDEX postings_transaction_idx ON postings(transaction_id);
```

File roles: `journal` is a year journal; `directives` covers the `NN-*.dat`
include files; `opening` covers `opening/*.journal`; `archive` is
`archived-manual.journal`. Every physical file is projected exactly once even
when included by multiple year journals. `archive` transactions are projected
(unmatch/undo tooling needs them) but MUST be excluded from balances,
registers, and aggregates — they intentionally duplicate matched manual
entries.

Cross-file reads (running balance, register) order transactions by
`(date, include-expansion position)`: top-level year journals in filename
order, each expanded depth-first at its `include` lines, then a stable sort
by date. For transactions inside one physical file this reduces to
`(date, journal_files.path, txn_order)`; the expansion walk exists because
included files must keep their include-site position — opening balances are
included at the top of the start-year journal and must sort before same-date
rows from the journal itself, which plain path ordering would invert. The
ordering is deterministic and matches insertion policy (reconciliation
assertions are inserted last on their date).

A transaction block ends at the first blank or non-indented line (ledger
semantics). Top-level comments following a block are file items, not block
content.

## Amount Storage

Ledger keeps amounts at full precision internally and rounds only when
serializing for presentation. Storage mirrors that discipline: amounts are
never stored at display precision.

- `postings.amount_nano` holds the amount as a 64-bit integer count of
  nanounits (10^-9 of one major unit): `USD -10.00` → `-10000000000`,
  `BTC 0.00042` → `420000`. Exact for any literal with nine or fewer
  decimal places; range is ±9.2 billion major units.
- Sums, running balances, and inferred elided amounts are computed in
  nanounits and stay exact — no float ever touches an amount.
- Rounding happens once, at serialization, using
  `commodities.display_scale` (derived from the commodity's `format`
  directive where present).
- A literal with more than nine decimal places is valid Ledger but outside
  the managed subset: the block is preserved raw and a diagnostic is
  recorded. Price/cost math (`@`, `@@`) likewise stays with the ledger CLI
  until explicitly supported.

When priced commodities (stocks, currency conversion) become managed,
prices should be stored as exact rationals — integer numerator/denominator
pairs (`price_num`, `price_den`, `price_commodity`, plus a unit-vs-total
kind for `@` vs `@@`) — because prices are ratios between commodities and
division rarely terminates in decimal. Rationals generalize nanounits (a
nanounit amount is just denominator 10^9). The two dimensions are stored
differently because they are used differently: amounts are *summed*, and
SQL can aggregate fixed-denominator integers but not arbitrary rationals;
prices are *multiplied*, and rational math (arbitrary-precision, e.g.
Python `fractions.Fraction`) stays exact through cost-basis and conversion
chains, rounding once at presentation — the same round-late rule.

SQLite note: there is no true decimal column type — `DECIMAL(10,2)` is
affinity only (stored as INTEGER/REAL), and IEEE floats drift on money.
Integer nanounits keep arithmetic exact in SQL and map 1:1 to Postgres
`BIGINT`.

## File Items

`journal_items` preserves the physical journal as an ordered document. It is
the layer that lets the app render a full file without losing file-level
comments, blank lines, includes, account/directive declarations, or unsupported
Ledger syntax.

Top-level material outside transaction blocks is represented as:

- `blank`
- `comment`
- `include`
- `directive`
- `raw`

Transaction blocks are represented as `transaction` items linked to
`transactions.id`.

Rendering policy:

- Untouched non-transaction items render `raw_text` byte-for-byte.
- Untouched transaction items may render original `raw_text`.
- Touched transaction items render from `transactions`, `postings`,
  `comments`, and `metadata_entries`.
- New transactions are inserted as new `journal_items` rows.
- Unsupported or unknown top-level material stays as `raw`.

This separates file-level comments from transaction/posting comments. File-level
comments are document structure; transaction/posting comments are semantic
metadata or preserved text inside a transaction block.

## Comments And Metadata

Comments are stored losslessly first. Parsed key/value metadata is a structured
view over comments, not a replacement for raw text.

`owner_type` is `transaction` or `posting`. `source_location` records where the
comment came from:

- `header_inline`
- `txn_comment`
- `posting_inline`
- `posting_comment`

```sql
CREATE TABLE comments (
    id TEXT PRIMARY KEY,
    owner_type TEXT NOT NULL CHECK (owner_type IN ('transaction', 'posting')),
    owner_id TEXT NOT NULL,
    comment_order INTEGER NOT NULL,
    source_location TEXT NOT NULL
        CHECK (source_location IN (
            'header_inline',
            'txn_comment',
            'posting_inline',
            'posting_comment'
        )),
    raw_text TEXT NOT NULL,
    parse_status TEXT NOT NULL DEFAULT 'raw'
        CHECK (parse_status IN ('kv', 'tag', 'raw', 'error')),
    parsed_key TEXT,
    parsed_value_text TEXT
);

CREATE INDEX comments_owner_idx ON comments(owner_type, owner_id, comment_order);
CREATE INDEX comments_key_idx ON comments(parsed_key);

CREATE TABLE metadata_entries (
    id TEXT PRIMARY KEY,
    comment_id TEXT NOT NULL UNIQUE REFERENCES comments(id) ON DELETE CASCADE,
    owner_type TEXT NOT NULL CHECK (owner_type IN ('transaction', 'posting')),
    owner_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value_text TEXT NOT NULL,
    value_type TEXT NOT NULL DEFAULT 'string'
        CHECK (value_type IN (
            'string',
            'date',
            'account',
            'amount',
            'boolean',
            'uuid',
            'json',
            'unknown'
        )),
    value_string TEXT,
    value_date TEXT,
    value_decimal TEXT,
    value_commodity TEXT,
    value_boolean BOOLEAN,
    source_location TEXT NOT NULL,
    source_order INTEGER NOT NULL
);

CREATE INDEX metadata_owner_idx ON metadata_entries(owner_type, owner_id);
CREATE INDEX metadata_key_idx ON metadata_entries(key);
CREATE INDEX metadata_key_value_idx ON metadata_entries(key, value_text);
```

Parser rule:

- `; key: value` becomes `comments.parse_status = 'kv'` and one
  `metadata_entries` row with `value_type = 'string'`.
- `; key:: value-expr` (ledger typed metadata) also becomes `'kv'`, with the
  expression parsed into the matching typed column and `value_type` set
  accordingly (`[date]` → `value_date`, amount → `value_decimal` +
  `value_commodity`, `true`/`false` → `value_boolean`).
- Rendering derives the form from the type: `value_type = 'string'` renders
  `key:`, typed values render `key::` — no separate flag needed. Untouched
  comments render from `raw_text` regardless.
- `; :flag:` ledger tags (e.g. `; :manual:`) become `parse_status = 'tag'`
  with the tag name in `parsed_key` and no value. The unknowns and unmatch
  flows depend on these, so they must round-trip exactly.
- A comment without a single key/value pair stays in `comments` only.
- Inline comments with multiple key/value pairs stay raw at first.
- App code should query `metadata_entries`, not parse raw comment text.

## Reference Data

The `NN-*.dat` files (`role = 'directives'`) declare accounts, payees, tags,
and commodities — they are what make `ledger --strict` / `--pedantic`
meaningful. Their directives stay losslessly in `journal_items`; the tables
below are the typed projection over them, same class as `transactions`:
wiped on rebuild, mutated only via parse/mutate/render of the owning file.

Rows are the union of **declarations** and **usage**:

- `declared` — the entity has a directive in a `.dat` file.
- `used` — the entity appears in at least one posting or transaction
  (ancestors of used accounts are synthesized as used).

`used AND NOT declared` is the `--pedantic` violation, computed as an
anti-join and recorded in `journal_diagnostics` with the offending file:line.
This replaces the `ledger accounts --count` shell-out for account lists and
enables pre-write validation and autocomplete from the database.

```sql
CREATE TABLE accounts (
    id TEXT PRIMARY KEY,
    journal_file_id TEXT REFERENCES journal_files(id) ON DELETE CASCADE,
    name TEXT NOT NULL UNIQUE,
    account_type TEXT NOT NULL
        CHECK (account_type IN ('assets', 'liabilities', 'income', 'expenses', 'equity', 'other')),
    subtype TEXT,
    parent_name TEXT,
    depth INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    closed_on TEXT,
    declared BOOLEAN NOT NULL DEFAULT FALSE,
    used BOOLEAN NOT NULL DEFAULT FALSE,
    managed_by_app BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX accounts_type_idx ON accounts(account_type, subtype);

CREATE TABLE payees (
    id TEXT PRIMARY KEY,
    journal_file_id TEXT REFERENCES journal_files(id) ON DELETE CASCADE,
    name TEXT NOT NULL UNIQUE,
    default_account TEXT,
    declared BOOLEAN NOT NULL DEFAULT FALSE,
    used BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE payee_aliases (
    id TEXT PRIMARY KEY,
    payee_id TEXT NOT NULL REFERENCES payees(id) ON DELETE CASCADE,
    pattern TEXT NOT NULL,
    alias_order INTEGER NOT NULL,
    UNIQUE (payee_id, pattern)
);

CREATE TABLE tags (
    id TEXT PRIMARY KEY,
    journal_file_id TEXT REFERENCES journal_files(id) ON DELETE CASCADE,
    name TEXT NOT NULL UNIQUE,
    note TEXT,
    declared BOOLEAN NOT NULL DEFAULT FALSE,
    used BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE commodities (
    id TEXT PRIMARY KEY,
    journal_file_id TEXT REFERENCES journal_files(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL UNIQUE,
    format TEXT,
    display_scale INTEGER NOT NULL DEFAULT 2,
    note TEXT,
    declared BOOLEAN NOT NULL DEFAULT FALSE,
    used BOOLEAN NOT NULL DEFAULT FALSE
);
```

### Account Hierarchy

The full name is a materialized path (`Assets:Wells Fargo:Checking`); there
is no `parent_id`. Renaming an account means rewriting posting lines anyway,
so an adjacency list buys nothing, and subtree queries are a prefix match:

```sql
WHERE name = :account OR name LIKE :account || ':%'
```

Segments cannot contain `:`, so the prefix test is unambiguous.
`account_type`, `parent_name`, and `depth` are derived from the name at
projection time (pure functions of `name`, rebuilt for free). Immediate
children — the "expand a tree node" and "pick a parent for a new account"
queries — are `WHERE parent_name = :account`, and lexicographic order on
`name` is depth-first tree order, so the picker needs no recursion.
Undeclared intermediate nodes (`Assets:Wells Fargo`) are synthesized as
`used` rows so the UI tree is complete; creating an account under a
not-yet-declared parent just declares the leaf and lets the parent
materialize the same way.

### Account Lifecycle

- **Closing** is app metadata (`; lf_closed:: [<date>]` → `closed_on`): hide
  the account from autocomplete and new-entry pickers, diagnose new postings
  dated after the close, leave history and reports untouched.
- **Deletion** removes the declaration from the `.dat`, allowed only when
  the usage anti-join shows no posting references the account or a
  descendant. Nothing has a foreign key into `accounts`; postings join by
  name by design.

### Merchant Layer

`payees` doubles as the merchant list (Monarch-style):

- On import, the app — not `ledger convert` — matches statement text against
  `payee_aliases` in `alias_order`. The journal's payee line gets the
  canonical merchant name; the raw statement text is preserved as
  `statement_payee` metadata. Merchant rollups are
  `GROUP BY transactions.payee` joined to `payees` by name.
- Categorization precedence: explicit rule → `payees.default_account` →
  `Expenses:Unknown`. Merchant defaults absorb the "normalize payee, set one
  category" rules; the rules engine keeps only the exceptions.
- Undeclared payees are allowed (manual entries, one-off checks);
  `used AND NOT declared` payees become a "create merchant from this payee?"
  suggestion surface, not an error.
- Lint: an alias pattern that matches a *different* merchant's canonical
  name is diagnosed — the one case where ledger's read-time aliasing could
  disagree with the app's import-time result.

## Rules

Rules move from `rules/20-match-rules.ndjson` into the database. They are
**operation tables** (app-authored, not derivable from journals): they
survive projection rebuilds and are covered by the durability export.

Condition semantics are two-level DNF: a rule matches when **any** group
matches, and a group matches when **all** of its conditions match. This
expresses `(payee LIKE 'WAL-MART%' AND amount < 20) OR (...)` directly; any
boolean expression normalizes into this shape.

```sql
CREATE TABLE rules (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL DEFAULT 'match',
    name TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    position INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE rule_condition_groups (
    id TEXT PRIMARY KEY,
    rule_id TEXT NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
    group_order INTEGER NOT NULL,
    UNIQUE (rule_id, group_order)
);

CREATE TABLE rule_conditions (
    id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL REFERENCES rule_condition_groups(id) ON DELETE CASCADE,
    condition_order INTEGER NOT NULL,
    field TEXT NOT NULL
        CHECK (field IN ('payee', 'merchant', 'date', 'amount', 'account')),
    operator TEXT NOT NULL,
    value TEXT NOT NULL,
    secondary_value TEXT,
    UNIQUE (group_id, condition_order)
);

CREATE TABLE rule_actions (
    id TEXT PRIMARY KEY,
    rule_id TEXT NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
    action_order INTEGER NOT NULL,
    action_type TEXT NOT NULL
        CHECK (action_type IN ('set_account', 'add_tag', 'set_kv', 'append_comment')),
    key TEXT,
    value TEXT NOT NULL,
    UNIQUE (rule_id, action_order)
);

CREATE INDEX rule_actions_value_idx ON rule_actions(action_type, value);
```

Seed once from the NDJSON (legacy flat condition chains split on `or`
joiners into groups — `and` binds tighter, so this yields the same DNF),
then delete the file. No id or history compatibility is required. Rule
create/edit/delete are recorded as operations.

## Imports

These tables replace the current `imported_transactions_v2` table and
`imports/import-log.ndjson` over time.

```sql
CREATE TABLE import_sources (
    id TEXT PRIMARY KEY,
    import_account_id TEXT NOT NULL,
    source_file_sha256 TEXT NOT NULL,
    original_path TEXT,
    archived_path TEXT,
    file_name TEXT NOT NULL,
    imported_at TEXT,
    UNIQUE (import_account_id, source_file_sha256)
);

CREATE TABLE import_identities (
    id TEXT PRIMARY KEY,
    import_account_id TEXT NOT NULL,
    source_identity TEXT NOT NULL,
    source_payload_hash TEXT,
    transaction_id TEXT REFERENCES transactions(id) ON DELETE SET NULL,
    import_source_id TEXT REFERENCES import_sources(id) ON DELETE SET NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    current_status TEXT NOT NULL DEFAULT 'active'
        CHECK (current_status IN ('active', 'undone', 'merged', 'missing')),
    UNIQUE (import_account_id, source_identity)
);

CREATE INDEX import_identities_txn_idx ON import_identities(transaction_id);
```

Classification semantics: duplicate detection treats
`current_status = 'undone'` as absent. Undoing an import flips its
identities to `undone` instead of deleting them (the audit survives), and
re-importing the same rows reactivates the identity (`active`, new
`transaction_id`, bumped `last_seen_at`). Without this rule an undone import
could never be re-imported. Merged duplicates keep one row per carried
identity, all pointing at the surviving transaction.

## Operations And Stages

Operations are durable app history. Stages are proposed work that may be
applied, refreshed, or discarded.

Operations fully replace `events.jsonl` and `imports/import-log.ndjson`:

- **Undo is forward-only compensation.** An undo is a new operation with
  `compensates_operation_id` pointing at the forward operation; "already
  undone" means a non-failed compensating operation exists. `status`
  describes only the operation's own lifecycle. This ports the current
  `*.compensated.v1` model and lets import undo and semantic undo share one
  spine.
- **Drift detection simplifies.** The last-known-hash chain scan of
  `events.jsonl` is replaced by comparing the on-disk hash with
  `journal_files.content_hash`; external edits are recorded in
  `journal_diagnostics`, and undo is refused when an operation's
  `operation_files.hash_after` no longer matches the current file.
- **The activity feed reads `operations`** ordered by `created_at`.
- **Operation ids are pre-minted** before the write so journal metadata and
  the operation share one id. The `reconciliation_event_id` journal key is
  renamed to `lf_operation_id` in the one-time journal migration (no
  compatibility constraints); the import fence scans for it via
  `metadata_entries`.
- **Existing `events.jsonl` history is not migrated.** Operations start
  fresh at cutover; the old file is deleted once the new path works.
- **Rule and reference-data mutations are operations too**, even though they
  are not journal mutations — one audit trail for everything the app
  changes.

```sql
CREATE TABLE operations (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    actor_type TEXT NOT NULL DEFAULT 'user'
        CHECK (actor_type IN ('user', 'system', 'ai')),
    actor_id TEXT,
    status TEXT NOT NULL DEFAULT 'applied'
        CHECK (status IN ('staged', 'applying', 'applied', 'failed', 'undone')),
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL,
    applied_at TEXT,
    base_revision TEXT,
    git_commit_sha TEXT,
    undo_mode TEXT NOT NULL DEFAULT 'exact'
        CHECK (undo_mode IN ('exact', 'semantic', 'unavailable')),
    compensates_operation_id TEXT REFERENCES operations(id),
    payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX operations_type_idx ON operations(type);
CREATE INDEX operations_created_idx ON operations(created_at);
CREATE INDEX operations_compensates_idx ON operations(compensates_operation_id);

CREATE TABLE operation_files (
    operation_id TEXT NOT NULL REFERENCES operations(id) ON DELETE CASCADE,
    journal_file_id TEXT REFERENCES journal_files(id) ON DELETE SET NULL,
    path TEXT NOT NULL,
    hash_before TEXT,
    hash_after TEXT,
    PRIMARY KEY (operation_id, path)
);

CREATE TABLE operation_entities (
    operation_id TEXT NOT NULL REFERENCES operations(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('transaction', 'posting')),
    entity_id TEXT NOT NULL,
    change_type TEXT NOT NULL
        CHECK (change_type IN ('created', 'updated', 'deleted', 'merged', 'split', 'preserved')),
    block_hash_before TEXT,
    block_hash_after TEXT,
    PRIMARY KEY (operation_id, entity_type, entity_id)
);

CREATE TABLE stages (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ready'
        CHECK (status IN ('ready', 'stale', 'applied', 'discarded', 'failed')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    base_revision TEXT,
    base_file_hashes_json TEXT NOT NULL DEFAULT '{}',
    summary_json TEXT NOT NULL DEFAULT '{}',
    payload_json TEXT NOT NULL,
    applied_operation_id TEXT REFERENCES operations(id) ON DELETE SET NULL
);
```

## Entity Survivorship

This table is optional for the first migration, but the schema should leave room
for it. File hashes remain the primary drift detector; survivorship lets the
app recover semantically when IDs survive a file edit.

```sql
CREATE TABLE entity_history (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('transaction', 'posting')),
    entity_id TEXT NOT NULL,
    operation_id TEXT REFERENCES operations(id) ON DELETE SET NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    from_file_path TEXT,
    to_file_path TEXT,
    from_block_hash TEXT,
    to_block_hash TEXT,
    successor_entity_id TEXT,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX entity_history_entity_idx ON entity_history(entity_type, entity_id, created_at);
CREATE INDEX entity_history_successor_idx ON entity_history(successor_entity_id);
```

## Diagnostics

Diagnostics make parse drift visible without blocking the whole app.

```sql
CREATE TABLE journal_diagnostics (
    id TEXT PRIMARY KEY,
    journal_file_id TEXT REFERENCES journal_files(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    line_number INTEGER,
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'error')),
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    blocking BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TEXT NOT NULL
);

CREATE INDEX diagnostics_file_idx ON journal_diagnostics(journal_file_id, line_number);
```

## Workspace Lock

For local SQLite, a lock table is mainly documentation plus stale-lock recovery.
The actual writer should also use a process/file lock around parse/mutate/render.

```sql
CREATE TABLE workspace_locks (
    workspace_id TEXT PRIMARY KEY,
    held_by TEXT NOT NULL,
    operation_id TEXT,
    acquired_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
```

## Rebuild Flow

Projection rebuild should:

1. Clear projection tables: `journal_files`, `journal_items`, `transactions`,
   `postings`, `comments`, `metadata_entries`, `accounts`, `payees`,
   `payee_aliases`, `tags`, `commodities`, and `journal_diagnostics`.
2. Parse journal files and includes, assigning each physical file its role;
   never project the same file twice.
3. Store every physical file item in `journal_items`, including blanks,
   comments, includes, directives, transaction blocks, and raw unsupported
   material.
4. Assign missing `lf_txn_id` / `lf_posting_id` only during explicit migration,
   not during passive rebuild.
5. Preserve raw comments and unsupported metadata.
6. Re-link `import_identities.transaction_id` by `lf_txn_id` and source
   metadata where possible.
7. Mark unresolved imported identities as `missing`, not deleted.
8. Rebuild reference data as the union of declarations and usage, then run
   the declared/used anti-joins into `journal_diagnostics`.

## Mutation-Time Projection

A full rebuild is the recovery path, not the write path. Every mutation
already flows through the journal writer's backup/verify/rollback ritual;
the projection hooks into it:

1. Parse/mutate/render the touched block(s) and write the file(s).
2. Re-project only the touched files inside one SQLite transaction, updating
   `journal_files.content_hash` last.
3. If the writer rolls back (backup restore), roll the SQLite transaction
   back with it. Files and projection commit or revert together.
4. On read, a mismatch between the disk hash and `content_hash` triggers
   re-projection of that file (self-healing after crashes or external
   edits).

This replaces the UI's positional mutation contract. Today the client
submits `(journalPath, lineNumber, headerLine)` and the server rejects on
any byte drift; stored line numbers go stale on every earlier edit in the
file. The new contract is `(lf_txn_id, raw_block_hash)`: locate the block by
id, reject as stale when the block hash differs. `source_start_line` /
`source_end_line` stay accurate because the touched file is re-projected on
every write.

## Durability

Projection tables are disposable; operation tables are not. Two rules:

1. The database lives in the active workspace (resolved from workspace
   config, not a process-level root), so all services and startup tasks open
   the same file.
2. Operation-class tables must reach the git safety net. The workspace
   `.gitignore` excludes `.workflow/`, so on the existing snapshot hooks
   (shutdown / 24h) the app exports the database — a text `.dump` to a
   git-tracked path diffs well and keeps the audit recoverable from git
   history alone.

## Incremental Adoption Plan

No backwards compatibility is required (alpha, single user): cutovers may
drop old files once the new path works, and one-time journal rewrites are
acceptable. Journals themselves are user data and always migrate; app-state
files do not.

1. Add schema migrations and create these tables beside the existing
   `imported_transactions_v2` table.
2. Build a parser projection that fills `journal_files`, `journal_items`,
   `transactions`, `postings`, `comments`, `metadata_entries`, and
   diagnostics.
3. Project reference data from the `NN-*.dat` files into `accounts`,
   `payees`, `payee_aliases`, `tags`, and `commodities`; wire the
   declared/used diagnostics. Drop the `NN-*` file naming convention in place
   of plain file names.
4. One-time journal migration: assign `lf_txn_id` / `lf_posting_id` and
   rename existing app metadata keys to house style (`source_identity` →
   `lf_source_identity`, `reconciliation_event_id` → `lf_operation_id`,
   etc.) in a single rewrite pass.
5. Replace import duplicate detection with `import_identities`
   (undone-as-absent semantics); drop `imported_transactions_v2`.
6. Move `.workflow/stages/*.json` into `stages`.
7. Cut over `events.jsonl` and `imports/import-log.ndjson` to `operations`,
   `operation_files`, `operation_entities`, and `import_sources`; port both
   undo paths to the compensation model; start history fresh and delete the
   old files.
8. Seed `rules` tables from `rules/20-match-rules.ndjson`, then delete it;
   route rule edits through operations.
9. Retire `payee_aliases.csv` and its generated `.dat`: payee and alias
   directives live in the payees `.dat`, projected into
   `payees`/`payee_aliases`; the import pipeline does app-side alias
   matching (merchant layer).
10. Replace line-oriented mutation paths with parse/project/mutate/render
    for touched blocks and switch the client contract to
    `(lf_txn_id, raw_block_hash)`.
11. Add the snapshot-hook database export to the git safety net.

## Further Consolidation Candidates

Other places the app keeps state in raw text or recomputes in Python that
the database can absorb. Not scheduled; each is a deliberate yes/no:

- **Tracked/import accounts out of `workspace.toml`.** `[tracked_accounts.*]`
  and `[import_accounts.*]` are app entities with lifecycle, edited by
  rewriting TOML today. As operation-class tables they get real ids, audit
  via operations, and a validated join to `accounts`. `workspace.toml`
  shrinks to bootstrap facts (dirs, base currency, workspace name).
- **Full-text search via FTS5.** Payee/notes/metadata search currently
  filters parsed rows in Python per request; an FTS5 index over
  `transactions.payee` + comments makes search a query.
- **Writer backups as pre-images.** The `.bak.*` file litter exists so the
  writer can roll back. Storing the pre-image text in `operation_files`
  gives rollback *and* `undo_mode = 'exact'` restore from the database, and
  the backup files disappear.
- **Delete the in-memory parse cache.** `get_transactions_cached` and its
  mtime invalidation are obsolete once reads hit the projection; the
  content-hash check is the invalidation.
- **Aggregates in SQL (ADR-0005).** Dashboard/activity/register numbers are
  Python loops over parsed rows today. `GROUP BY` over `postings` is the
  deferred Explore aggregation engine's substrate — served directly by the
  nanounit amount storage.
- **Category-suggestion stats.** Payee-similarity suggestions rescan history
  per request; a small stats view (payee → account frequencies) makes them a
  lookup.

## Revision 2 (2026-07-03)

Updated after a backend review against the current implementation. No
backwards compatibility is required (alpha). Changes:

- `journal_files.role` gains explicit values and an exclusion policy
  (`archived-manual.journal` is projected but never feeds balances).
- Deterministic cross-file ordering defined for running balance.
- Amounts stored as integer nanounits (`postings.amount_nano`), rounded
  only at presentation via `commodities.display_scale` — ledger's
  round-late semantics.
- Flag-tag comments (`; :manual:`) are representable
  (`comments.parse_status = 'tag'`).
- Typed app metadata serializes with ledger's `::` value-expression syntax
  (parse-time validation by ledger); strings keep single-colon form.
- Reference data tables added: `accounts` (type/subtype, closing,
  materialized-path hierarchy), `payees` + `payee_aliases` (merchant layer
  with default accounts), `tags`, `commodities` — all with declared/used
  flags and `--pedantic`-equivalent diagnostics.
- Rules move from NDJSON into `rules` / `rule_condition_groups` /
  `rule_conditions` / `rule_actions` with two-level DNF group semantics.
- `operations` gains `compensates_operation_id` and fully replaces
  `events.jsonl`: compensation-based undo, drift via `content_hash`,
  activity feed, pre-minted operation ids (`lf_operation_id` in journal
  text).
- `import_identities` treats `undone` as absent so undone imports can be
  re-imported.
- Mutation-time incremental projection defined; client mutation contract
  moves from `(journalPath, lineNumber, headerLine)` to
  `(lf_txn_id, raw_block_hash)`.
- Durability: database is workspace-scoped and exported to a git-tracked
  dump on the existing snapshot hooks.
- Further consolidation candidates listed (tracked accounts out of TOML,
  FTS5 search, pre-images instead of `.bak` files, SQL aggregates per
  ADR-0005).

Amendment (2026-07-04, adoption step 2 implementation): cross-file ordering
is `(date, include-expansion position)` rather than raw
`(date, path, txn_order)` — included files keep their include-site position
so opening balances sort before same-date year-journal rows. Block boundary
clarified: a transaction block ends at the first blank or non-indented line.
