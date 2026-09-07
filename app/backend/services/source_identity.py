"""The identity of one imported bank row (issue #007, seam 2).

A *source identity* answers one question: "is this CSV row the same bank row
as one I already have?" Everything that computes, stores, reads, or compares
that answer lives here, because the three incidents in issue #007 all came
from those concerns being spread out:

* The identity base omitted the amount whenever the institution posting's
  amount was elided, so two genuinely different purchases at one merchant on
  one day hashed identically. :func:`institution_amount` derives the elided
  amount instead of yielding ``""``, and :func:`compute` refuses to hash an
  amount it could not determine.
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
  drift is still possible; ``suffix_of`` below is the intended replacement for
  them and currently has no production callers.

Generations
-----------

Identities written before the amount fix are *generation 1*: their hash was
computed over a base whose amount field may be empty. Generation 2 hashes a
canonical decimal amount. :meth:`SourceIdentity.value` is what new writes
store; :meth:`SourceIdentity.legacy_value` reproduces what generation 1 would
have stored for the same row, so a re-import still recognises rows imported
before the fix without rewriting any journal data.

``legacy_value`` is only safe for recognising a row, never for asserting two
rows are distinct — a generation-1 hash is ambiguous by construction. Callers
comparing against stored identities must treat a legacy-only match whose
payload hash differs as *ambiguous*, not as a duplicate.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
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

CURRENT_GENERATION = 2


class IdentityInputError(ValueError):
    """An identity was requested for a row whose amount could not be determined.

    Raised rather than hashing a blank: a blank amount is what made two
    distinct transactions collide, and a row we cannot identify must fail
    loudly instead of being quietly mis-identified.
    """


@dataclass(frozen=True)
class SourceIdentity:
    """One bank row's identity, in both the current and the legacy generation."""

    value: str
    legacy_value: str
    generation: int = CURRENT_GENERATION

    def matches(self, stored: str | None) -> bool:
        """Does *stored* (a value read from journal metadata or the identity
        store) refer to this same row, in either generation?"""
        if not stored:
            return False
        return stored == self.value or stored == self.legacy_value

    def is_legacy_only_match(self, stored: str | None) -> bool:
        """*stored* matches only via the ambiguous generation-1 hash.

        Callers use this to tell "certainly the same row" from "the same row
        under a hash that could not tell rows apart".
        """
        if not stored:
            return False
        return stored != self.value and stored == self.legacy_value


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_payee(payee: str) -> str:
    """Collapse whitespace and case so the same row exported by two different
    statement formats still identifies as one row."""
    return re.sub(r"\s+", " ", (payee or "").strip().lower())


def suffix_of(key: str) -> str | None:
    """The carried-duplicate suffix of an identity or payload key.

    ``"lf_source_identity"`` → ``"1"``; ``"lf_source_identity_2"`` → ``"2"``;
    a key from neither family → ``None``. Intended to replace the four
    implementations that currently have to agree — see the module docstring;
    none of them call this yet.
    """
    match = IDENTITY_KEY_RE.match(key) or PAYLOAD_HASH_KEY_RE.match(key)
    if match is None:
        return None
    return match.group("suffix") or "1"


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


def canonical_amount(amount: Decimal) -> str:
    """The amount's identity form: a plain signed decimal, no commodity.

    Generation 1 hashed whatever string the posting happened to carry
    (``"USD -7.92"``, ``"-7.92"``, or ``""``). Hashing a normalized ``Decimal``
    makes the identity independent of how the amount was rendered.
    """
    normalized = amount.normalize()
    # ``normalize`` renders small integers in exponent form (``1E+2``); expand.
    if normalized == normalized.to_integral_value():
        normalized = normalized.quantize(Decimal(1))
    return format(normalized, "f")


@dataclass(frozen=True)
class IdentityInputs:
    """Everything :func:`compute` needs, recovered from a written journal block."""

    import_account_id: str
    date: str
    statement_payee: str
    amount: Decimal


def statement_payee_from_csv_row(row: str | None) -> str | None:
    """Raw statement description from a ``; CSV:`` metadata row.

    The intermediate CSV columns are ``date,code,description,amount,total,note``;
    the description is the payee as the institution wrote it, before any
    merchant aliasing.
    """
    if not row:
        return None
    import csv as _csv

    try:
        fields = next(_csv.reader([row]))
    except (StopIteration, _csv.Error):
        return None
    if len(fields) < 3:
        return None
    return fields[2].strip() or None


def _csv_date(row: str | None) -> str | None:
    if not row:
        return None
    import csv as _csv

    try:
        fields = next(_csv.reader([row]))
    except (StopIteration, _csv.Error):
        return None
    return (fields[0].strip() or None) if fields else None


def inputs_from_block(
    *,
    metadata: dict[str, str],
    postings: list[dict],
    institution_account: str,
) -> IdentityInputs:
    """Recover a written block's identity inputs, for recomputation.

    The block carries its own provenance: ``import_account_id`` names the
    account, and the ``; CSV:`` line preserves the statement row verbatim, so
    date and statement payee come from the source rather than from a header
    that merchant aliasing may since have rewritten.

    Raises:
        IdentityInputError: the block lacks provenance, or its postings no
            longer include the import account (so the amount cannot be trusted).
            Both cases need a human decision rather than a guess.
    """
    import_account_id = str(metadata.get("import_account_id") or "").strip()
    if not import_account_id:
        raise IdentityInputError("block has no import_account_id")

    row = metadata.get("csv")
    date = _csv_date(row)
    statement_payee = statement_payee_from_csv_row(row)
    if not date or not statement_payee:
        raise IdentityInputError("block has no usable ; CSV: provenance row")

    if not any(
        str(posting.get("account", "")).strip() == institution_account
        for posting in postings
    ):
        raise IdentityInputError(
            f"no posting to the import account {institution_account!r} "
            "(the account was reassigned, so the amount is not comparable)"
        )

    amount = institution_amount(postings, institution_account)
    if amount is None:
        raise IdentityInputError("institution amount is indeterminable")

    return IdentityInputs(
        import_account_id=import_account_id,
        date=date,
        statement_payee=statement_payee,
        amount=amount,
    )


def compute(
    *,
    import_account_id: str,
    date: str,
    statement_payee: str,
    amount: Decimal | None,
    raw_amount: str = "",
) -> SourceIdentity:
    """The identity of one imported row.

    Args:
        import_account_id: the import account the row arrived on — identities
            are scoped per account, so two accounts may hold the same row.
        date: the row's date, as written in the source (``2026/04/27``).
        statement_payee: the description exactly as the statement gave it,
            before any merchant-alias rewriting.
        amount: the institution-account amount, from :func:`institution_amount`.
        raw_amount: the generation-1 amount string, needed only to reproduce
            the legacy hash for rows imported before the amount fix.

    Raises:
        IdentityInputError: *amount* is ``None``. A row whose amount cannot be
            determined has no trustworthy identity.
    """
    if amount is None:
        raise IdentityInputError(
            "Cannot compute a source identity without an amount "
            f"(account={import_account_id!r}, date={date!r}, payee={statement_payee!r}). "
            "An identity without an amount cannot tell two same-day purchases apart."
        )

    payee = normalize_payee(statement_payee)
    # Written as literal f-strings so the hashed base is readable as-is: these
    # two expressions define what "the same bank row" means.
    value = _sha256_text(f"{import_account_id}|{date}|{payee}|{canonical_amount(amount)}")
    legacy_value = _sha256_text(f"{import_account_id}|{date}|{payee}|{raw_amount}")
    return SourceIdentity(value=value, legacy_value=legacy_value)
