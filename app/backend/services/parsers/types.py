from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Iterator, Protocol, runtime_checkable


@dataclass
class Record:
    """Normalized output from an Adapter, input to a Translator.

    Cash fields are signed from the account holder's perspective:
    positive = money in, negative = money out.
    """
    date: date
    description: str

    amount: Decimal | None = None
    currency: str = "USD"
    counterparty: str | None = None
    code: str | None = None
    effective_date: date | None = None

    # Reserved for future aggregator adapters (Plaid, SimpleFIN, GoCardless).
    # CSV adapters leave these as defaults.
    provider_id: str | None = None
    pending: bool = False
    suggested_category: str | None = None
    provider_payee: str | None = None

    # Populated by CSV adapters when the source CSV exposes a running-balance
    # column and a free-text note column. Left as defaults otherwise.
    balance: Decimal | None = None
    note: str | None = None

    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Posting:
    account: str
    amount: Decimal | None = None
    commodity: str | None = None
    price: Decimal | None = None


@dataclass
class LedgerTransaction:
    date: date
    payee: str
    postings: list[Posting]
    effective_date: date | None = None
    code: str | None = None
    note: str | None = None
    balance: Decimal | None = None


@runtime_checkable
class Adapter(Protocol):
    name: str
    institution: str
    formats: tuple[str, ...]
    # translator_name: str — class attribute naming the translator this adapter
    # pairs with. Required by the dispatch seam in csv_normalizer.

    def parse(self, text: str) -> Iterator[Record]: ...
    # matches(text, filename) -> bool is optional; adapters may omit it.
    # Account binding is the routing mechanism; autodetect is a future feature.


@runtime_checkable
class Translator(Protocol):
    name: str

    def translate(self, record: Record, account: str) -> LedgerTransaction: ...
