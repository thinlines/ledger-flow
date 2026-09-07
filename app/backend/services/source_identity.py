"""The identity of one imported bank row (issue #007, seam 2).

A *source identity* answers one question: "is this CSV row the same bank row
as one I already have?" Everything that computes, stores, reads, or compares
that answer lives here, because the three incidents in issue #007 all came
from those concerns being spread out:

* The identity base omitted the amount whenever the institution posting's
  amount was elided, so two genuinely different purchases at one merchant on
  one day hashed identically. :func:`_institution_amount` derives the elided
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
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal

from .currency_parser import parse_optional_amount

#: The whole interface. Everything else is how this module keeps its promises —
#: the suffix convention, the hashing details, the amount derivation.
__all__ = [
    "IDENTITY_KEY",
    "PAYLOAD_HASH_KEY",
    "IdentityInputError",
    "IdentityVariant",
    "carry_onto",
    "of_journal_block",
    "of_statement_row",
    "suffix_of",
    "variants_of",
]

# The journal key names, in one place. Everything that reads or writes import
# provenance metadata uses these rather than spelling the names out again.
IDENTITY_KEY = "lf_source_identity"
PAYLOAD_HASH_KEY = "source_payload_hash"

_SOURCE_FILE_KEY = "source_file_sha256"
_IMPORTER_VERSION_KEY = "importer_version"

# The four key families that together describe one carried source row. They move
# in lockstep: a variant is written, read and removed as a set. Callers never
# name them — they go through IdentityVariant.
_CARRIED_KEY_BASES = (IDENTITY_KEY, PAYLOAD_HASH_KEY, _SOURCE_FILE_KEY, _IMPORTER_VERSION_KEY)

_CARRIED_KEY_RE = re.compile(
    rf"^(?P<base>{'|'.join(_CARRIED_KEY_BASES)})(?:_(?P<suffix>\d+))?$"
)


class IdentityInputError(ValueError):
    """An identity was requested for a row whose amount could not be determined.

    Raised rather than hashing a blank: a blank amount is what made two
    distinct transactions collide, and a row we cannot identify must fail
    loudly instead of being quietly mis-identified.
    """


def _carried_key(base: str, suffix: int) -> str:
    """The metadata key for *base* at *suffix*.

    Suffix 1 is the unsuffixed key — ``_carried_key(IDENTITY_KEY, 1)`` is
    ``"lf_source_identity"``, and only 2 upward take ``_N``. That asymmetry is
    the convention every reader used to reimplement, usually as ``or "1"``.
    """
    if base not in _CARRIED_KEY_BASES:
        raise ValueError(f"{base!r} is not a carried key family")
    return base if suffix == 1 else f"{base}_{suffix}"


def _carried_keys(suffix: int) -> frozenset[str]:
    """Every key belonging to the carried row at *suffix*.

    Removing a variant means removing this whole set: leaving a stray
    ``source_payload_hash_2`` behind an erased identity is how a block starts
    disagreeing with itself.
    """
    return frozenset(_carried_key(base, suffix) for base in _CARRIED_KEY_BASES)


def suffix_of(key: str) -> int | None:
    """Which carried row *key* belongs to, or ``None`` if it belongs to none.

    ``"lf_source_identity"`` and ``"importer_version"`` → 1;
    ``"source_payload_hash_2"`` → 2; ``"lf_txn_id"`` → ``None``.
    """
    match = _CARRIED_KEY_RE.match(key)
    if match is None:
        return None
    return int(match.group("suffix") or 1)


@dataclass(frozen=True)
class IdentityVariant:
    """One source row a journal block claims to be.

    A block normally claims one. It claims several when duplicates were merged:
    the survivor keeps its own identity at suffix 1 and carries each absorbed
    row's at 2, 3, … so a re-import of any of their source files still
    recognises the merged block instead of writing the row again.
    """

    suffix: int
    identity: str
    payload_hash: str | None = None
    source_file_sha256: str | None = None
    importer_version: str | None = None

    @property
    def keys(self) -> frozenset[str]:
        """The metadata keys this variant occupies."""
        return _carried_keys(self.suffix)

    def _fields(self) -> tuple[tuple[str, str], tuple[str, str | None], ...]:
        return (
            (IDENTITY_KEY, self.identity),
            (PAYLOAD_HASH_KEY, self.payload_hash),
            (_SOURCE_FILE_KEY, self.source_file_sha256),
            (_IMPORTER_VERSION_KEY, self.importer_version),
        )


def _clean(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def variants_of(metadata: Mapping[str, object]) -> tuple[IdentityVariant, ...]:
    """Every source row *metadata* claims, in suffix order.

    A suffix with no identity yields nothing, however many of its other keys are
    present — an identity is what makes a variant a variant. The first element is
    the block's primary row, which is what a caller wanting "the" identity should
    take.
    """
    by_suffix: dict[int, dict[str, str | None]] = {}
    for key, value in metadata.items():
        match = _CARRIED_KEY_RE.match(str(key).strip().lower())
        if match is None:
            continue
        suffix = int(match.group("suffix") or 1)
        by_suffix.setdefault(suffix, {})[match.group("base")] = _clean(value)

    variants = []
    for suffix in sorted(by_suffix):
        fields = by_suffix[suffix]
        identity = fields.get(IDENTITY_KEY)
        if not identity:
            continue
        variants.append(
            IdentityVariant(
                suffix=suffix,
                identity=identity,
                payload_hash=fields.get(PAYLOAD_HASH_KEY),
                source_file_sha256=fields.get(_SOURCE_FILE_KEY),
                importer_version=fields.get(_IMPORTER_VERSION_KEY),
            )
        )
    return tuple(variants)


def _next_free_suffix(metadata: Mapping[str, object]) -> int:
    """The lowest carried slot *metadata* has not used, never below 2.

    Slot 1 belongs to the block's own row and is never handed out.
    """
    used = {variant.suffix for variant in variants_of(metadata)}
    suffix = 2
    while suffix in used or _carried_key(IDENTITY_KEY, suffix) in metadata:
        suffix += 1
    return suffix


def carry_onto(
    existing: Mapping[str, object],
    variants: Iterable[IdentityVariant],
) -> tuple[tuple[str, str], ...]:
    """The metadata to add so the *existing* block also claims *variants*.

    Returns ``(key, value)`` pairs in write order. A variant whose identity the
    block already claims is skipped, so merging the same row twice adds nothing;
    the rest take consecutive free slots. Fields the absorbed row did not carry
    are simply absent, and the four families stay aligned on their shared slot.
    """
    claimed = {variant.identity for variant in variants_of(existing)}
    suffix = _next_free_suffix(existing)
    out: list[tuple[str, str]] = []
    for variant in variants:
        if variant.identity in claimed:
            continue
        out.extend(
            (_carried_key(base, suffix), value)
            for base, value in variant._fields()
            if value
        )
        claimed.add(variant.identity)
        suffix += 1
    return tuple(out)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_payee(payee: str) -> str:
    """Collapse whitespace and case so the same row exported by two different
    statement formats still identifies as one row."""
    return re.sub(r"\s+", " ", (payee or "").strip().lower())


def _institution_amount(
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
    amount = _institution_amount(postings, institution_account)
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
