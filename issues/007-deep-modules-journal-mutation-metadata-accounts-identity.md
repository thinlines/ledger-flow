---
labels: [architecture, reliability]
---

# Deep modules for journal mutation, metadata, accounts, and import identity

## Why this exists

Three separate data-integrity incidents in this workspace traced back to the same
structural gap, not to three unrelated bugs:

1. **331 transactions carried no `lf_txn_id`.** A hand-run rename of
   `source_identity` → `lf_source_identity` did half of what
   `journal_migration_service` does. The projection silently fell back to
   `_short_id("txn", rel_path, txn_order, raw_block_hash)` — a content-and-position
   address. Editing a block changed its id; inserting a transaction changed the id of
   every block below it. **No diagnostic fired**, because a block with no stable
   identity is treated as normal.

2. **13 groups of transactions shared one `lf_source_identity`.** Reproduced the hash:
   the identity base for the 2026-04-27 Costco pair is
   `wells_fargo_credit_card_9867|2026/04/27|costco whse #0761 boise id|` — the amount
   field is **empty**. `_extract_institution_amount` finds the institution posting and
   returns its amount, but the importer elides that posting's amount, so it returns
   `""`; the `if postings:` fallback never fires because the account matched. Ten of
   those groups are legitimate distinct transactions colliding. This is live, and the
   consequence is data loss rather than noise: a colliding row classifies as
   `"conflict"` with `conflictReason == "identity_collision"`, which
   `_build_fence_conflicts` excludes from the UI ("identity-collision rows … never
   reach the UI"), `duplicateCount` folds into the duplicate tally, and only
   `matchStatus == "new"` rows are written. A genuine new purchase sharing
   account + date + payee with any existing transaction is therefore **silently
   dropped, and reported as a duplicate**.

3. **Three genuine duplicates were written by a one-day reader/data mismatch.**
   Commit `1bdfacb` (2026-07-04 21:57) changed `SOURCE_IDENTITY_KEY_RE` from
   `^source_identity(_N)?$` to `^lf_source_identity(_N)?$`, and changed the writer to
   emit the prefixed key. The journal's existing blocks still carried the *unprefixed*
   key — `journal_migration_service` was not run against this workspace until
   2026-09-06. On 2026-07-05 an import (source file `d7fc789f…`) ran in that gap:
   `_existing_identity_map_from_journal` matched **nothing**, dedupe fell back to the
   `import_identities` DB map alone, and every row absent from it classified as
   `"new"` and was written. The first journal commit containing `lf_source_identity`
   (`ba04d5f`, 2026-07-05) is that import's own output.

   The reader's key name and the data's key name disagreed for two months with no
   registry binding them and no diagnostic noticing. That is this issue in miniature.

Related, found while investigating:

- **All 133 `import_identities.transaction_id` values are NULL.**
  `transactions.journal_file_id` cascades from `journal_files`, `_delete_file_rows`
  deletes that row on every re-projection, and `import_identities.transaction_id` is
  `ON DELETE SET NULL`. Since `load_transactions_projected` refreshes on every request,
  the column can never hold a value. Adoption step 6 of the projection schema
  ("re-link `import_identities.transaction_id` by `lf_txn_id`") was specified and never
  implemented.
- **`import_identities` is unrebuildable.** It lives in gitignored `.workflow/state.db`
  and is not in `operation_dump_service._DURABLE_TABLES`. Losing the DB loses every
  `current_status` bit (`undone` / `merged`), which nothing else records.
  `_build_existing_map` *does* merge a journal-derived identity map with the DB map, so
  dedupe is not blind to journal-only identities — but that map is built from **the
  target year's journal only**, so a cross-year import sees none of them, and it is
  silently empty whenever the journal's key names drift from the reader's (incident 3).
- **Startup validates nothing.** `lifespan` runs stage cleanup, a git snapshot, and
  embedding warmup. No projection refresh, no integrity check.

## The structural diagnosis

`journal_writer.mutate` is the model deep module in this codebase: a small interface
(`config`, `paths`, `tag`, `event_type`, optional `verify`) over a large implementation
(hash, backup, mutate, verify, re-project, record operation, rollback with per-path
failure aggregation, files-and-projection committing together).

It owns the **file**-level ritual. Nothing owns the **block**-level ritual. So every
caller does this *inside* the `with` block:

```python
lines = path.read_text(encoding="utf-8").splitlines()   # 11 services
start, end = locate_block_by_id(lines, txn_id)          # or by hash, or by substring
... splice lines by hand ...
path.write_text("\n".join(lines) + "\n")
```

That one missing layer produces every smell in the backend:

| Smell | Measurement |
|---|---|
| Shotgun surgery | read/locate/splice/write reimplemented in **11 services** + **6 `main.py` endpoints** inline (`/transactions/unmatch` = 11 raw-surgery hits in a 163-line body) |
| Module envy | `.get("ledger_account")` **51×** across **17 modules**; `.get("display_name")` 32×; the ledger-account → tracked-account reverse lookup hand-rolled ~20× |
| Shallow modules | `journal_syntax` exports 6 regexes and hides nothing; `journal_block_service` exports 5 helpers callers must sequence themselves |
| Divergent copies | metadata parsing reimplemented 6× (one does not lowercase keys, one handles `::`, two bypass the parser with substring matching); metadata writing 4×; the `_2` suffix family as 4 unsynchronised regexes |
| Divergent registries | `workspace_service.SYSTEM_TAGS` (26 keys) vs `manual_entry_service.SYSTEM_METADATA_KEYS` (14) — neither a superset. `lf_match_id` is in **neither**, so it never reaches `12-tags.dat` and `_extract_user_metadata_lines` misclassifies it as a user comment. `lf_subtype`, `lf_closed`, `lf_default_account` are in neither either. `12-tags.dat` generation is append-only, so renamed keys are never retired. |

Naming is a symptom of the same thing. `docs/ledger-flow-projection-schema.md:31` says
app-owned keys use the `lf_` prefix; `statement_payee`, `import_account_id`,
`institution_template`, `source_payload_hash`, `source_file_sha256`, `importer_version`,
`transfer_*`, `match-id`, `minimum_payment`, `statement_period` and `tracked_account_id`
do not. The schema doc's own example at line 51 shows `; statement_payee:` unprefixed,
contradicting its rule. `journal_migration_service` renamed only two families by design
("schema-named keys only"), leaving the rest for "the issue that owns their flow" —
this is that issue.

## What to build

### 1. `Account` on `AppConfig` — remove the envy

`AppConfig` already proves the pattern with `csv_dir` / `journal_dir` properties; it
stops short of accounts and hands out raw TOML dicts instead.

```python
@dataclass(frozen=True)
class Account:
    id: str
    display_name: str
    ledger_account: str
    subtype: str | None
    institution: str | None
    last4: str | None
    import_account_id: str | None

config.accounts                        -> tuple[Account, ...]
config.account(account_id)             -> Account | None
config.account_for_ledger(ledger_name) -> Account | None   # the ~20 hand-rolled loops
```

Mechanical, low risk, deletes the most call sites of anything here. First because the
block editor should be written against a clean account abstraction, not retrofitted to
one.

### 2. `SourceIdentity` — the module the April bug proves is missing

```python
def compute(account_id, date, statement_payee, amount) -> SourceIdentity  # rejects empty amount
def parse(metadata) -> SourceIdentity | None                              # incl. _N suffix family
def compare(a, b) -> Literal["same", "conflict", "distinct"]
```

Refusing to build an identity from an empty amount is the fix. Making it a module is
what stops the next variant. Note the migration question: once fixed, the 463 existing
identities are computed under the old rule and will not match newly computed ones —
prefer a versioned key (`lf_source_identity` carrying its algorithm generation) over a
silent rewrite of 463 hashes.

### 3. `edit_transaction` — the block-level seam (the large one)

```python
with journal_writer.mutate(config=config, paths=[p], tag="recategorize",
                           event_type="transaction.recategorized.v1") as mut:
    with edit_transaction(config, txn_id, expect_hash=block_hash) as txn:
        txn.set_category("Expenses:Groceries")
        txn.set_metadata("lf_match_id", match_id)
        txn.clear_metadata("lf_match_id")
        txn.set_status("cleared")
    mut.summary = txn.describe()
```

Behind ~7 methods: locating by `lf_txn_id` with hash fallback, the staleness check,
reading and splicing the block, metadata insertion position, `:` vs `::` rendering,
line-ending and blank-run preservation, posting rewrites.

Deletion test: delete it and the complexity reappears in 17 places — it is already
there in 17 places.

### 4. `journal_metadata` — the key/value layer beneath the editor

`parse` / `upsert` / `render` / `is_app_owned` / `family`. One registry replaces the two
divergent lists and becomes the source for `12-tags.dat` generation (so renamed keys can
finally be retired). One suffix-family function replaces the four regexes.

Build it *with* the block editor, not before — its main consumer is the editor, and
building it standalone means guessing at the interface.

### 5. `check_integrity` — the invariant registry

One interface, `check_integrity(config) -> list[Finding]`, that every invariant
registers against: missing `lf_txn_id`; duplicate `lf_source_identity` with differing
`source_payload_hash`; journal vs `import_identities` divergence; orphaned
`transaction_id`; ledger `--strict` disagreement. Surface it on startup — this is what
should have caught all three incidents.

### 6. Follow-on fixes unblocked by the above

- Backfill `import_identities` from journal metadata during `refresh_projection`
  (undone-as-absent makes journal presence sufficient evidence of `active`).
- Add `import_identities` + `import_sources` to `_DURABLE_TABLES`.
- Fix or drop the `transaction_id` FK.
- Dedupe *within* an import batch, not only against the pre-batch snapshot.
- Make `"conflict"` block the write rather than warn.
- Finish the `lf_` rename by extending `_KEY_RENAMES`, and fix the schema doc's
  self-contradicting example at line 51.

## On using the ledger CLI instead

Considered and rejected for both reading and writing.

- **Writing:** `ledger xact` prints a *draft* transaction to stdout inferred from a
  prior one. It cannot target an existing block, upsert metadata, or preserve
  surrounding bytes. There is no write path to adopt.
- **Reading:** ledger's output (`csv`, `xml`, `--format`) is *evaluated* postings, not
  source text. Routing the read path through it forfeits byte-level fidelity, line
  numbers, comment ordering, and preservation of unknown user comments — exactly what
  `journal_items.raw_text` and `render_file`'s byte-identical round-trip exist to
  protect. Tags are reachable via `tag('…')` only if keys are enumerated in advance, and
  `::` values come back evaluated.
- **Decisive:** none of the incidents was a parsing failure. The parser read the file
  correctly — it found all 464 identities and all 383 missing ids. Every failure was an
  *invariant* failure. Swapping the parser changes none of them.

The CLI does have a real role: as an **oracle at a second seam** — confirming balances
and totals the app computed, and running `--strict` / `--pedantic` for undeclared
accounts and tags. `ledger_runner` already exists for this.

## Sequencing

`Account` → `SourceIdentity` → `edit_transaction` → `journal_metadata` → `check_integrity`,
then the follow-on fixes. Each step gives the next a real abstraction to build on, and
gives `check_integrity` a real invariant to check.

## Progress

### Seam 1 — `Account` (landed)

`services/config_service.py` gains `Account`, `AppConfig.accounts`,
`.import_account_entries`, `.account()`, `.account_for_ledger()`,
`.import_account()` and `.ledger_account_for()`, indexed via `cached_property`
so the reverse lookup is O(1) rather than a scan per posting. Covered by
`tests/test_config_accounts.py` (14 tests), including the first-wins precedence
the hand-rolled loops already had and the `load_config` path that *derives*
tracked accounts from import accounts.

Converted: `transaction_helpers`, `reconciliation_service`, `dashboard_service`,
`direction_service`, `unified_transactions_service`, `account_register_service`,
`import_service`, and three sites in `main.py`.

| Metric | Before | After |
|---|---|---|
| `.get("ledger_account")` in services + `main.py` | 51 | 32 (4 of them the definition in `config_service`) |
| Hand-rolled ledger-account reverse lookups | ~20 | 1 |
| Backend tests | 1057 | 1071 |
| Pre-existing ruff findings | 45 | 45 (none introduced) |

**One reverse lookup deliberately left**, at `unknowns_service.py:123`.
`_build_transaction_records` takes `import_accounts` / `tracked_accounts` as
parameters *and* an optional `config`, and fabricates an `AppConfig` with empty
account dicts when `config is None`. Converting `_tracked_account_context` to
read from `config` would silently change that fallback path. It is a symptom of
the same problem — two sources of truth for account data in one function — and
should be resolved when `unknowns_service` is restructured for the block editor
(seam 3), not before.

The remaining 28 `.get("ledger_account")` sites are single reads on a config
dict the caller already holds (chiefly `workspace_service`, which *writes*
config back to TOML and correctly stays dict-based). They are not envy and do
not need converting.

### Seam 2 — `SourceIdentity` (landed)

`services/source_identity.py` is now the only place that *computes* an import
identity. It owns `IDENTITY_KEY` / `PAYLOAD_HASH_KEY` and their suffix-family
regexes (`import_service` re-exports them), `normalize_payee`, `suffix_of`,
`institution_amount`, `canonical_amount` and `compute`.

**Naming is not yet consolidated.** Only `import_service` was rewired. The key
name is still spelled independently in `import_history_service` (two regexes),
`reconciliation_context_service` (two), `manual_entry_service` (one),
`journal_migration_service` (one), and as `startswith` checks in
`reconciliation_duplicate_service` — so the drift that caused incident 3 is
still structurally possible. `suffix_of` exists to replace them and has no
production callers yet.

Fixes:

- `institution_amount` derives the **elided** institution posting's amount by
  negating the counter-postings — the value ledger itself would infer — instead
  of returning `""`. This is the 2026-04-27 Costco collision.
- `compute` raises `IdentityInputError` rather than hashing a blank amount. A row
  whose amount cannot be determined now fails loudly.
- Generation 2 hashes a canonical `Decimal`, so `USD -7.92`, `-7.92` and
  `-7.920` identify as one row. Generation 1 hashed whatever string the posting
  carried, which is why identity was sensitive to rendering.

Generation handling — the journal was **migrated**, not versioned. A
compatibility path was written first (`compute` returned both the new hash and
a generation-1 `legacy_value`, and `_classify_transaction` tried each in turn)
and then removed once the migration had run. Measured before the migration, it
would not have been enough on its own:

| Stored identity reproduced by | rows |
|---|---|
| the current hash | 0 |
| `legacy_value` | 304 |
| neither (written by still-earlier formulas) | 153 |
| unknown — no `; CSV:` provenance to recompute from | 3 |

Two-thirds coverage, so 153 rows would still have re-imported as `"new"`. That
shortfall is why the migration below was chosen over carrying the compat path.

A legacy-only match whose payload hash differs is recorded as
`conflictReason == "legacy_identity_ambiguous"` rather than being treated as a
duplicate, because a generation-1 hash cannot tell two same-day purchases at one
merchant apart.

| Metric | Before | After |
|---|---|---|
| Places computing an import identity | 1 inline expression, 0 tests | 1 module, 43 tests |
| Identity key regexes | 4 (unsynchronised) | 5 (1 authoritative, 4 not yet rewired) |
| Stored identities a re-import reproduces | 0 of 460 | 457 of 460 |
| Backend tests | 1071 | 1112 |
| Pre-existing ruff findings | 45 | 45 |

#### Journal history to be rewritten to one generation — **written, not yet run**

The migration below is implemented, tested, and exposed on the CLI. **It has not
been executed against this workspace**; every identity in `journals/2026.journal`
is still generation 1, unchanged since it was first written. Verified by
comparing identity values across every journal snapshot back to `ba04d5f`
(2026-07-06): no `lf_source_identity` value has ever changed.

Chosen over carrying the legacy-compat path indefinitely, because that path is
not sufficient on its own: of 457 identities with provenance, **153 cannot be
reproduced by `legacy_value` either**, having been written by still-earlier
identity formulas. Those rows were *already* unrecognisable on re-import before
any of this work — a live duplication risk, latent since the formula last
changed.

`journal_migration_service.migrate_source_identities(config, dry_run=...)`
recomputes every stored identity from each block's own `; CSV:` provenance —
`import_account_id`, the statement date and description as the institution wrote
them, and the institution posting's amount (deriving the elided value). Exposed as
`ledger-flow migrate-source-identities [--dry-run]`.

It refuses to guess. A block with no provenance row, or whose postings no longer
include its import account (the account was reassigned, so the amount is not
comparable), is left untouched and reported. Blocks resolving to one identity are
reported as collisions — genuine same-row duplicates needing triage.

Dry-run result on this workspace: **457 would be rewritten, 0 unchanged, 0
collisions, 3 skipped** (2026-02-17 ACH rows with no `; CSV:` line), touching
`journals/2026.journal` only.

Zero collisions is the substantive finding: every imported row *would* get a
unique identity, which the pre-fix scheme could not express.

Run and committed: 457 rewritten, 3 skipped, 0 collisions, touching only the
457 identity lines. A second run rewrites nothing. The legacy generation
machinery has since been removed — `legacy_value`, `SourceIdentity` itself,
`CURRENT_GENERATION`, `compute`'s `raw_amount`, `sourceIdentityLegacy`, the
legacy branch of `_classify_transaction`, and the `legacy_identity_ambiguous`
reason. `compute` now returns the hash directly.

The three provenance-less ACH blocks keep identities that no formula in the
module reproduces. They were unmatchable before the migration too; removing the
legacy path did not change their status. Still to be triaged.

#### The two paths disagreed on the amount's sign

Found while removing the legacy path, by checking the thing that had never been
checked: whether a re-import reproduces what the migration wrote. It did not —
**437 of 460 rows disagreed**, and journal-derived dedupe matched 0 of 56
previewed rows. Dedupe was surviving only on the gitignored
`.workflow/state.db`.

Two defects, compounding, both on the import side:

- `_parse_transaction` dropped amount-less postings. `ACCOUNT_LINE_RE` needs a
  two-space separator after the account, and `ledger convert` writes the elided
  institution posting bare, so the posting list held only the counter-posting.
  Every other reader of the same block — `_block_metadata_and_postings` among
  them — falls back to `ACCOUNT_ONLY_RE` and keeps it.
- `institution_amount`'s "no institution posting" branch then returned the
  first posting's amount *unchanged*. For a deposit written
  `Income:Employer  USD -975.70` the institution amount is +975.70; it returned
  -975.70. The branch was documented as "matching the pre-existing behaviour",
  which was true of generation 1 and precisely the thing being replaced.

So the importer hashed `+296.79` where the migration hashed `-296.79`. Both
paths are now consistent: `_parse_transaction` records bare postings with an
empty amount, and the fallback derives the negated sum like the main path.
Verified against the live workspace — 457 of 460 stored identities are
reproduced by the import path, the 3 exceptions being the ACH blocks above, and
54 of 56 previewed rows are now recognised from the journal alone.

The committed journal needed no correction: the migration path was the correct
one throughout.

**Open decision — needs a product call.** Ambiguous rows are classified but not
yet surfaced: `_build_fence_conflicts` still returns only
`reconciled_date_fence` rows, and the frontend does not render the `conflicts`
list at all. So a legacy-ambiguous row is still silently skipped at write time.
Options: (a) surface ambiguous rows in the import UI for a per-row decision —
safest, needs frontend work; (b) write them and let the existing duplicate
review flow catch them; (c) leave them skipped and rely on `check_integrity`
(seam 5) to report them after the fact. Until this is decided, the underlying
"silently dropped" behaviour persists for rows colliding with **pre-fix** data
only — newly written identities are unambiguous.

They are no longer *traceless*, at least: `_emit_identity_collision_events` now
keys off "conflict that is not a date fence" rather than the literal
`identity_collision` reason, so an ambiguous row emits an
`import.identity_collision.v1` operation carrying its `conflict_reason` and the
identity it matched under. Running the migration removes the case entirely.

## Acceptance criteria

- [x] `Account` dataclass and `AppConfig.accounts` / `.account()` / `.account_for_ledger()` exist and are covered by tests
- [x] No service reimplements the ledger-account → tracked-account reverse lookup — one site remains, documented above with its reason
- [x] `.get("ledger_account")` no longer appears in service modules for *resolving* tracked/import accounts; remaining uses are config serialization
- [x] Source identity refuses an empty amount and is computed in exactly one place
- [x] Existing identities are migrated or versioned, with the choice recorded — migrated
- [x] Journal history rewritten to one identity generation (457 rows, 0 collisions)
- [x] Legacy generation machinery removed
- [x] The import path and the migration path compute the same identity for the same row
- [ ] Identity key names come from one registry — only `import_service` rewired so far
- [ ] Ambiguous legacy-identity rows are surfaced rather than silently skipped (open decision, above; they are now at least logged)
- [ ] 3 provenance-less ACH blocks triaged (they keep pre-fix identities)
- [ ] Journal block editing happens in exactly one module; no service or endpoint calls `read_text().splitlines()` on a journal to edit a transaction
- [ ] Metadata parsing and writing happen in exactly one module; one key registry drives `12-tags.dat`
- [ ] `check_integrity` exists, runs on startup, and reports all five invariants
- [ ] `ledger -f journals/<year>.journal bal` exits 0 with no warnings after each step
- [ ] Backend test suite passes (baseline: 1057 tests)
