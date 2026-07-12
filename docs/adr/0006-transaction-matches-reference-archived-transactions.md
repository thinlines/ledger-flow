# Transaction matches reference archived transactions

When an imported transaction replaces a manual transaction during duplicate
resolution, Ledger Flow models that relationship as a first-class transaction
match. The journal remains canonical: the match identity is written as
`lf_match_id` transaction metadata on both the surviving imported transaction
and the archived manual transaction, and SQLite projects it into an indexed match row. The
match references the surviving imported transaction and the archived manual
transaction as projected transactions, rather than embedding the manual journal
block in the match row. This keeps archived manual entries inspectable through
the same projection model while letting block hashes guard unmatch against
later edits.

The match projection is active-only and rebuildable from the current journal
state. When a match is reversed, the `lf_match_id` metadata is removed from the
surviving imported transaction and the manual transaction is restored without
the match metadata; the historical fact that a match was created and then
reversed belongs in operations, not in `transaction_matches`.

`lf_match_id` is the durable relationship key, serialized as a typed id with a
`match_` prefix. It must survive ordinary edits
to either transaction's shape, such as payee, category, posting, or note
changes. Block hashes are staleness guards for a single mutation attempt, not
part of match identity and not persisted as match keys.

Each match is one-to-one: one imported transaction can have at most one manual
match, and one archived manual transaction can have at most one imported match.
Imported/imported duplicate merging remains represented by carried import
identities, not by transaction matches.

Application flows should resolve matches through the indexed SQLite projection,
using the projected match id and transaction ids. They should not scan journal
text or archived files as the lookup mechanism.

New writes use `lf_match_id` so app-owned match metadata follows the `lf_`
convention. Projection rebuilds continue to recognize the legacy `match-id`
key, preserving unmatch for existing workspaces without requiring a passive
projection refresh to rewrite canonical journals.
