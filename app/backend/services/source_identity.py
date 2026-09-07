"""The identity of one imported bank row (issue #007, seam 2).

A *source identity* answers one question: "is this CSV row the same bank row
as one I already have?" Everything that computes, stores, reads, or compares
that answer lives here, because the three incidents in issue #007 all came
from those concerns being spread out:

* The identity base omitted the amount whenever the institution posting's
  amount was elided, so two genuinely different purchases at one merchant on
  one day hashed identically. :func:`institution_amount` derives the elided
  amount instead of yielding ``""``, and both entry points refuse to hash an
  amount they could not determine.
* The journal key name (``lf_source_identity``) lived in one regex here, a
  different regex in ``manual_entry_service``, and two more in
  ``import_history_service``. When one changed, the others did not, and the
  reader stopped seeing data it had itself written.

  This module is intended to be that one home, but **the consolidation is not
  finished**: only ``import_service`` reads its keys from here. Independent
  spellings still live in ``import_history_service`` (two regexes),
  ``reconciliation_context_service`` (two), ``manual_entry_service`` (one),
  ``journal_migration_service`` (one), and as ``startswith`` checks in
  ``reconciliation_duplicate_service``. Until those are rewired the original
  drift is still possible.

All stored identities are on one generation. The pre-fix hashes were rewritten
in place by ``journal_migration_service.migrate_source_identities`` (457 rows),
so there is no compatibility path here and a stored value either equals what
this module produces or refers to a different row.

Two entry points, one call each, differing only in where the row is read from:
:func:`of_statement_row` for a row arriving from an import, and
:func:`of_journal_block` for one recovered from a block already written. Both
derive the institution amount themselves — that identity is keyed on the
institution's own amount is this module's business, not its callers'.
"""

from __future__ import annotations

import csv
import hashlib
import re
from decimal import Decimal

from .currency_parser import parse_optional_amount

# The journal key names, in one place. Everything that reads or writes import
# provenance metadata uses these rather than spelling the names out again.
IDENTITY_KEY = "lf_source_identity"
PAYLOAD_HASH_KEY = "source_payload_hash"

#: ``lf_source_identity`` and its carried-duplicate family (``…_2``, ``…_3``).
IDENTITY_KEY_RE = re.compile(rf"^{IDENTITY_KEY}(?:_(?P<suffix>\d+))?$")
#: ``source_payload_hash`` and its matching family.
PAYLOAD_HASH_KEY_RE = re.compile(rf"^{PAYLOAD_HASH_KEY}(?:_(?P<suffix>\d+))?$")


class IdentityInputError(ValueError):
    """An identity was requested for a row whose amount could not be determined.

    Raised rather than hashing a blank: a blank amount is what made two
    distinct transactions collide, and a row we cannot identify must fail
    loudly instead of being quietly mis-identified.
    """


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_payee(payee: str) -> str:
    """Collapse whitespace and case so the same row exported by two different
    statement formats still identifies as one row."""
    return re.sub(r"\s+", " ", (payee or "").strip().lower())


def institution_amount(
    postings: list[dict],
    institution_account: str,
) -> Decimal | None:
    """The amount posted to the institution's own account.

    Ledger lets the last posting of a balanced transaction elide its amount,
    and the importer writes institution postings that way. Reading the raw
    field then yields ``""``. When the institution posting is blank and every
    other posting has an amount, the elided value is the negation of their
    sum — which is what ledger itself would infer.

    Returns ``None`` only when the amount is genuinely indeterminable.
    """
    target = (institution_account or "").strip()
    institution_index: int | None = None
    for index, posting in enumerate(postings):
        if str(posting.get("account", "")).strip() == target:
            institution_index = index
            break

    if institution_index is None:
        # No posting names the institution account. Its amount is still the
        # negated sum of the others — the transaction balances either way — so
        # derive it rather than returning a counter-posting's amount unchanged.
        # Returning it unchanged is a sign error: for a deposit written as
        # ``Income:Employer  USD -975.70``, the institution amount is +975.70.
        others = [
            parse_optional_amount(str(posting.get("amount", ""))) for posting in postings
        ]
        if not others or any(amount is None for amount in others):
            return None
        return -sum(others, Decimal(0))

    own = parse_optional_amount(str(postings[institution_index].get("amount", "")))
    if own is not None:
        return own

    others = [
        parse_optional_amount(str(posting.get("amount", "")))
        for index, posting in enumerate(postings)
        if index != institution_index
    ]
    if not others or any(amount is None for amount in others):
        return None
    return -sum(others, Decimal(0))


def _canonical_amount(amount: Decimal) -> str:
    """The amount's identity form: a plain signed decimal, no commodity.

    The pre-fix hash took whatever string the posting happened to carry
    (``"USD -7.92"``, ``"-7.92"``, or ``""``). Hashing a normalized ``Decimal``
    makes the identity independent of how the amount was rendered.
    """
    normalized = amount.normalize()
    # ``normalize`` renders small integers in exponent form (``1E+2``); expand.
    if normalized == normalized.to_integral_value():
        normalized = normalized.quantize(Decimal(1))
    return format(normalized, "f")


def _csv_provenance(row: str | None) -> tuple[str, str] | None:
    """The statement date and description from a ``; CSV:`` metadata row.

    The intermediate CSV columns are ``date,code,description,amount,total,note``.
    The description is the payee as the institution wrote it, before any merchant
    aliasing — which is why identity reads it from here and not from the block
    header, where an alias declared later may since have replaced it.

    ``None`` when the row is absent, unparseable, or missing either field.
    """
    if not row:
        return None
    try:
        fields = next(csv.reader([row]))
    except (StopIteration, csv.Error):
        return None
    if len(fields) < 3:
        return None
    date = fields[0].strip()
    payee = fields[2].strip()
    return (date, payee) if date and payee else None


def _hash(import_account_id: str, date: str, statement_payee: str, amount: Decimal) -> str:
    # Written as a literal f-string so the hashed base is readable as-is: this
    # expression defines what "the same bank row" means.
    base = f"{import_account_id}|{date}|{_normalize_payee(statement_payee)}|{_canonical_amount(amount)}"
    return _sha256_text(base)


def of_statement_row(
    *,
    import_account_id: str,
    date: str,
    statement_payee: str,
    postings: list[dict],
    institution_account: str,
) -> str:
    """The identity of a row arriving from an import.

    Args:
        import_account_id: the import account the row arrived on — identities
            are scoped per account, so two accounts may hold the same row.
        date: the row's date, as written in the source (``2026/04/27``).
        statement_payee: the description exactly as the statement gave it,
            before any merchant-alias rewriting.
        postings: the row's postings, from which the institution amount is
            derived. The institution posting may elide its amount.
        institution_account: the ledger account the institution posts to.

    Raises:
        IdentityInputError: the institution amount could not be determined. A
            row with no trustworthy amount has no trustworthy identity — that
            is what let two same-day purchases at one merchant collide.
    """
    amount = institution_amount(postings, institution_account)
    if amount is None:
        raise IdentityInputError(
            "Cannot compute a source identity without an amount "
            f"(account={import_account_id!r}, date={date!r}, payee={statement_payee!r}). "
            "An identity without an amount cannot tell two same-day purchases apart."
        )
    return _hash(import_account_id, date, statement_payee, amount)


def of_journal_block(
    *,
    metadata: dict[str, str],
    postings: list[dict],
    institution_account: str,
) -> str:
    """The identity of a row recovered from a block already written.

    The block carries its own provenance: ``import_account_id`` names the
    account and the ``; CSV:`` line preserves the statement row verbatim, so
    date and payee come from the source rather than from a header that merchant
    aliasing may since have rewritten. The result is byte-identical to what
    :func:`of_statement_row` produced when the block was first imported —
    that equality is what makes re-import recognise the row.

    Raises:
        IdentityInputError: the block lacks provenance, or its postings no
            longer include the import account, so the amount is not comparable.
            Both need a human decision rather than a guess.
    """
    import_account_id = str(metadata.get("import_account_id") or "").strip()
    if not import_account_id:
        raise IdentityInputError("block has no import_account_id")

    provenance = _csv_provenance(metadata.get("csv"))
    if provenance is None:
        raise IdentityInputError("block has no usable ; CSV: provenance row")
    date, statement_payee = provenance

    if not any(
        str(posting.get("account", "")).strip() == institution_account
        for posting in postings
    ):
        raise IdentityInputError(
            f"no posting to the import account {institution_account!r} "
            "(the account was reassigned, so the amount is not comparable)"
        )

    return of_statement_row(
        import_account_id=import_account_id,
        date=date,
        statement_payee=statement_payee,
        postings=postings,
        institution_account=institution_account,
    )
