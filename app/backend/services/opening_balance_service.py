from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from .journal_query_service import LF_TXN_ID_META_RE

from .config_service import AppConfig, infer_account_kind
from .currency_parser import parse_optional_amount


from .journal_block_service import lf_txn_id_line, mint_lf_txn_id
from .projection_db import connect, database_path
from .projection_service import refresh_projection

OPENING_BALANCES_EQUITY = "Equity:Opening-Balances"
OPENING_BALANCES_INDEX = "_opening_balances.journal"


@dataclass(frozen=True)
class OpeningBalanceEntry:
    tracked_account_id: str | None
    ledger_account: str
    offset_account: str
    amount: Decimal
    date: str
    minimum_payment: Decimal | None = None


def _parse_amount(raw: str) -> Decimal | None:
    return parse_optional_amount(raw)


def load_opening_balance_entries(config: AppConfig) -> list[OpeningBalanceEntry]:
    refresh_projection(config)
    entries: list[OpeningBalanceEntry] = []
    with connect(database_path(config)) as conn:
        rows = conn.execute(
            """
            SELECT transactions.id, transactions.date, postings.posting_order,
                   postings.account, postings.amount_nano, postings.amount_inferred,
                   tracked.value_text AS tracked_account_id,
                   minimum.value_text AS minimum_payment
            FROM transactions
            JOIN journal_files ON journal_files.id = transactions.journal_file_id
            JOIN postings ON postings.transaction_id = transactions.id
            LEFT JOIN metadata_entries AS tracked
              ON tracked.owner_type = 'transaction' AND tracked.owner_id = transactions.id
             AND tracked.key = 'tracked_account_id'
            LEFT JOIN metadata_entries AS minimum
              ON minimum.owner_type = 'transaction' AND minimum.owner_id = transactions.id
             AND minimum.key = 'minimum_payment'
            WHERE journal_files.role = 'opening'
            ORDER BY journal_files.path, transactions.txn_order, postings.posting_order
            """
        ).fetchall()

    grouped: dict[str, list] = {}
    for row in rows:
        grouped.setdefault(row[0], []).append(row)
    for txn_rows in grouped.values():
        primary = next(
            (row for row in txn_rows if not row[5] and row[4] is not None
             and infer_account_kind(row[3]) in {"asset", "liability"}),
            None,
        )
        if primary is None:
            continue
        offset = next((row[3] for row in txn_rows if row[2] != primary[2]), OPENING_BALANCES_EQUITY)
        entries.append(OpeningBalanceEntry(
            tracked_account_id=primary[6].strip() or None if primary[6] is not None else None,
            ledger_account=primary[3],
            offset_account=offset,
            amount=(Decimal(primary[4]) / Decimal(1_000_000_000)).quantize(
                Decimal("0.01")
            ),
            date=primary[1],
            minimum_payment=_parse_amount(primary[7]) if primary[7] is not None else None,
        ))
    return entries


def opening_balance_index(config: AppConfig) -> tuple[dict[str, OpeningBalanceEntry], dict[str, OpeningBalanceEntry]]:
    by_account_id: dict[str, OpeningBalanceEntry] = {}
    by_ledger_account: dict[str, OpeningBalanceEntry] = {}
    for entry in load_opening_balance_entries(config):
        if entry.tracked_account_id:
            by_account_id[entry.tracked_account_id] = entry
        by_ledger_account[entry.ledger_account] = entry
    return by_account_id, by_ledger_account


def _format_amount(amount: Decimal) -> str:
    return f"{amount.quantize(Decimal('0.01'))}"


def _default_opening_date(config: AppConfig) -> str:
    return f"{config.start_year:04d}-01-01"


def opening_balance_index_path(config: AppConfig) -> Path:
    return config.opening_bal_dir / OPENING_BALANCES_INDEX


def sync_opening_balance_include_index(config: AppConfig) -> None:
    index_path = opening_balance_index_path(config)
    include_lines = [
        f"include {journal_path.name}"
        for journal_path in sorted(config.opening_bal_dir.glob("*.journal"))
        if journal_path.name != OPENING_BALANCES_INDEX
    ]
    text = ("\n".join(include_lines) + "\n") if include_lines else ""
    if index_path.exists() and index_path.read_text(encoding="utf-8") == text:
        return
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(text, encoding="utf-8")


def write_opening_balance(
    config: AppConfig,
    tracked_account_id: str,
    ledger_account: str,
    amount_text: str,
    opening_date: str | None = None,
    offset_account: str = OPENING_BALANCES_EQUITY,
    minimum_payment: str | None = None,
) -> None:
    cleaned_amount = amount_text.strip()
    target_path = config.opening_bal_dir / f"{tracked_account_id}.journal"

    if not cleaned_amount:
        if target_path.exists():
            target_path.unlink()
        sync_opening_balance_include_index(config)
        return

    amount = _parse_amount(cleaned_amount)
    if amount is None:
        if target_path.exists():
            target_path.unlink()
        sync_opening_balance_include_index(config)
        return

    date = (opening_date or "").strip() or _default_opening_date(config)
    offset_ledger_account = offset_account.strip() or OPENING_BALANCES_EQUITY
    currency = str(config.workspace.get("base_currency", "USD")).strip() or "USD"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    # Upsert semantics: an amount edit rewrites the block, but its identity
    # must survive — reuse the existing lf_txn_id when the file has one.
    txn_id = mint_lf_txn_id()
    if target_path.exists():
        for line in target_path.read_text(encoding="utf-8").splitlines():
            existing_id = LF_TXN_ID_META_RE.match(line)
            if existing_id:
                txn_id = existing_id.group(1)
                break
    meta_lines = [
        lf_txn_id_line(txn_id),
        f"    ; tracked_account_id: {tracked_account_id}",
    ]
    cleaned_min_payment = (minimum_payment or "").strip()
    if cleaned_min_payment:
        parsed_min_payment = _parse_amount(cleaned_min_payment)
        if parsed_min_payment is not None:
            meta_lines.append(f"    ; minimum_payment: {_format_amount(parsed_min_payment)}")
    target_path.write_text(
        "\n".join(
            [
                f"{date} Opening balance",
                *meta_lines,
                f"    {ledger_account}  {currency} {_format_amount(amount)}",
                f"    {offset_ledger_account}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    sync_opening_balance_include_index(config)


def delete_opening_balance(config: AppConfig, tracked_account_id: str) -> None:
    target_path = config.opening_bal_dir / f"{tracked_account_id}.journal"
    if target_path.exists():
        target_path.unlink()
    sync_opening_balance_include_index(config)
