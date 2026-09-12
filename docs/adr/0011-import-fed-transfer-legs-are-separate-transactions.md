# Import-fed transfer legs are separate transactions

A transfer between two tracked accounts that both receive imports is recorded
as two transactions, one per side, each dated by its own bank and each posting
against the pair's in-transit account (`Assets:Transfers:<a>__<b>`). The two
are joined by shared `transfer_id` / `transfer_peer_account_id` metadata and a
`transfer_match_state` that moves from `pending` (one side present) to
`matched` (both present). The in-transit account's balance is, by
construction, the money currently between institutions. The register
collapses a matched pair into one row at read time; the journal never merges
them.

A transfer where at most one side is import-fed is a single transaction
posting directly between the two ledger accounts (`transfer_type: direct`).
There is only one bank date, so nothing needs to be held in transit.

## Rejected: merging both imported legs into one transaction

The obvious simplification — one transaction, two tracked postings, per-posting
effective dates (`; [=YYYY-MM-DD]`) to carry each bank's date, no in-transit
account — was considered and rejected for two independent reasons.

**Balance assertions are evaluated in parse order, not by effective date.**
`ledger` checks `= amount` assertions as it loads the journal, before any
reporting option applies; `--effective` never reaches them. A merged transfer
has one position in the file, so both legs post at that moment for assertion
purposes. Reconciling the receiving account for a period that ends between the
two bank dates then fails against a correct statement, because the app places
the assertion after the transfer in date order and `ledger` sees the incoming
leg as already posted. Dating the merged transaction on the later side mirrors
the failure onto the sending account. No single transaction date satisfies
both banks, which is the whole reason the money is in transit.

**Effective dates already carry reporting semantics.** `[=date]` means "report
this posting in a different period" — the canonical use is spreading a single
charge across the months it covers. Validating tracked-account balances under
`--effective` would read those reporting dates as settlement dates, and any
journal using effective dates for their actual purpose would produce running
balances that disagree with the bank. The two meanings cannot share one
syntax.

The consequence to keep in mind: the pairing logic in the register (grouped
settlement, bilateral matching) is the cost of reconciling both sides
truthfully, not an artifact to eliminate. Residuals such as transfer fees are
recorded as their own postings draining the in-transit account, not by
merging the legs.

See ADR-0006 for the parallel rule that transaction matches reference two
projected transactions rather than embedding one in the other.
