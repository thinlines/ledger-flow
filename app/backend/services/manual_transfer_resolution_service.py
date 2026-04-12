from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .transaction_helpers import (
    bilateral_matched_pending_transfer_orders as _bilateral_matched_pending_transfer_orders,
    grouped_settled_pending_transfer_orders as _grouped_settled_pending_transfer_orders,
)
from .backup_service import backup_file
from .config_service import AppConfig
from .import_profile_service import import_source_summary
from .import_service import (
    IMPORTER_VERSION,
    _build_existing_map,
    _classify_transaction,
    _merge_transaction_blocks,
    _parse_transaction as parse_import_transaction,
    _render_journal_text,
    _split_journal_preamble_and_transactions,
)
from .journal_query_service import _parse_transaction as parse_journal_transaction
from .journal_query_service import amount_to_number, load_transactions
from .transfer_service import (
    MANUAL_TRANSFER_RESOLUTION_METADATA_KEY,
    MANUAL_TRANSFER_RESOLUTION_METADATA_VALUE,
    TRANSFER_MATCH_STATE_MATCHED,
    build_import_match_transfer_metadata_updates,
    parse_manual_transfer_resolution_token,
    parse_metadata_lines,
    parse_transfer_metadata,
    transfer_pair_account,
    upsert_transaction_metadata,
)


RESOLUTION_WARNING = "Use this only when no imported counterpart is expected."


@dataclass(frozen=True)
class LocatedSourceTransaction:
    journal_path: Path
    preamble_lines: list[str]
    transaction_blocks: list[list[str]]
    block_index: int
    block_lines: list[str]
    metadata: dict[str, str]


@dataclass(frozen=True)
class ManualTransferResolutionPlan:
    resolution_token: str
    journal_path: Path
    journal_preamble_lines: list[str]
    journal_transaction_blocks: list[list[str]]
    source_block_index: int
    source_updated_lines: list[str]
    counterpart_lines: list[str]
    counterpart_source_identity: str
    counterpart_source_payload_hash: str
    peer_import_account_id: str
    amount: Decimal
    posted_on: str
    payee: str
    from_account_id: str
    from_account_name: str
    to_account_id: str
    to_account_name: str
    source_account_id: str
    source_account_name: str
    destination_account_id: str
    destination_account_name: str


def _tracked_account_id_for_import_account(config: AppConfig, import_account_id: str) -> str | None:
    import_account = config.import_accounts.get(import_account_id)
    if import_account is None:
        return None
    tracked_account_id = str(import_account.get("tracked_account_id", "")).strip() or import_account_id
    return tracked_account_id or None


def _tracked_account_details(config: AppConfig, tracked_account_id: str) -> tuple[str, str]:
    tracked_account = config.tracked_accounts.get(tracked_account_id)
    if tracked_account is None:
        raise ValueError(f"Tracked account not found: {tracked_account_id}")
    display_name = str(tracked_account.get("display_name", tracked_account_id)).strip() or tracked_account_id
    ledger_account = str(tracked_account.get("ledger_account", "")).strip()
    if not ledger_account:
        raise ValueError(f"Tracked account is missing a ledger account: {tracked_account_id}")
    return display_name, ledger_account


def _format_amount(amount: Decimal, commodity: str | None, base_currency: str) -> str:
    commodity_text = str(commodity or "").strip() or base_currency
    return f"{commodity_text} {amount.quantize(Decimal('0.01'))}"


def _find_source_transaction(config: AppConfig, resolution_token: str) -> LocatedSourceTransaction:
    token = parse_manual_transfer_resolution_token(resolution_token)
    matches: list[LocatedSourceTransaction] = []
    for journal_path in sorted(config.journal_dir.glob("*.journal")):
        if not journal_path.exists():
            continue
        preamble_lines, transaction_blocks = _split_journal_preamble_and_transactions(
            journal_path.read_text(encoding="utf-8")
        )
        for block_index, block_lines in enumerate(transaction_blocks):
            metadata = parse_metadata_lines(block_lines[1:])
            if str(metadata.get("import_account_id") or "").strip() != token["importAccountId"]:
                continue
            if str(metadata.get("source_identity") or "").strip() != token["sourceIdentity"]:
                continue
            matches.append(
                LocatedSourceTransaction(
                    journal_path=journal_path,
                    preamble_lines=preamble_lines,
                    transaction_blocks=transaction_blocks,
                    block_index=block_index,
                    block_lines=block_lines,
                    metadata=metadata,
                )
            )

    if not matches:
        raise ValueError("This pending transfer is no longer available to resolve manually.")
    if len(matches) > 1:
        raise ValueError("This pending transfer is no longer uniquely identifiable.")
    return matches[0]


def _assert_not_auto_resolved(config: AppConfig, import_account_id: str, source_identity: str) -> None:
    transactions = load_transactions(config)
    grouped_settled_orders = _grouped_settled_pending_transfer_orders(config, transactions)
    bilateral_matched_orders = _bilateral_matched_pending_transfer_orders(config, transactions, grouped_settled_orders)

    matching_orders = [
        order
        for order, transaction in enumerate(transactions)
        if str(transaction.metadata.get("import_account_id") or "").strip() == import_account_id
        and str(transaction.metadata.get("source_identity") or "").strip() == source_identity
    ]
    if len(matching_orders) != 1:
        raise ValueError("This pending transfer is no longer uniquely identifiable.")
    if matching_orders[0] in grouped_settled_orders or matching_orders[0] in bilateral_matched_orders:
        raise ValueError("This pending transfer is already handled automatically and cannot be resolved manually.")


def _build_resolution_plan(config: AppConfig, resolution_token: str) -> ManualTransferResolutionPlan:
    token = parse_manual_transfer_resolution_token(resolution_token)
    located = _find_source_transaction(config, resolution_token)
    _assert_not_auto_resolved(config, token["importAccountId"], token["sourceIdentity"])

    parsed_source = parse_journal_transaction(located.block_lines)
    if parsed_source is None:
        raise ValueError("The pending transfer could not be re-read safely.")

    source_tracked_account_id = _tracked_account_id_for_import_account(config, token["importAccountId"])
    if source_tracked_account_id is None:
        raise ValueError("The imported source account is no longer configured.")
    source_account_name, source_ledger_account = _tracked_account_details(config, source_tracked_account_id)

    transfer = parse_transfer_metadata(located.metadata, config.tracked_accounts)
    if not (
        transfer.is_import_match
        and transfer.transfer_match_state == "pending"
        and transfer.transfer_id == token["transferId"]
        and transfer.peer_account_id == token["peerAccountId"]
    ):
        raise ValueError("This transfer is no longer eligible for manual resolution.")

    if source_tracked_account_id == token["peerAccountId"]:
        raise ValueError("This transfer is no longer eligible for manual resolution.")

    peer_account = config.tracked_accounts.get(token["peerAccountId"])
    if peer_account is None:
        raise ValueError("The destination account is no longer available.")
    peer_import_account_id = str(peer_account.get("import_account_id") or "").strip()
    if not peer_import_account_id:
        raise ValueError("The destination account no longer has import matching configured.")
    peer_account_name, peer_ledger_account = _tracked_account_details(config, token["peerAccountId"])

    source_postings = [
        posting
        for posting in parsed_source.postings
        if posting.account == source_ledger_account and posting.amount is not None
    ]
    transfer_postings = [
        posting
        for posting in parsed_source.postings
        if posting.account == transfer_pair_account(source_tracked_account_id, token["peerAccountId"])
        and posting.amount is not None
    ]
    if len(source_postings) != 1 or len(transfer_postings) != 1:
        raise ValueError("The pending transfer could not be re-read safely.")

    source_amount = source_postings[0].amount
    transfer_amount = transfer_postings[0].amount
    if source_amount is None or transfer_amount is None or source_amount + transfer_amount != Decimal("0"):
        raise ValueError("The pending transfer could not be re-read safely.")

    base_currency = str(config.workspace.get("base_currency", "USD"))
    transfer_account = transfer_postings[0].account
    counterpart_core_lines = [
        located.block_lines[0],
        f"    {transfer_account}  {_format_amount(source_amount, transfer_postings[0].commodity, base_currency)}",
        f"    {peer_ledger_account}  {_format_amount(-source_amount, source_postings[0].commodity, base_currency)}",
    ]

    counterpart_identity = parse_import_transaction(
        counterpart_core_lines,
        peer_import_account_id,
        peer_ledger_account,
        base_currency=base_currency,
    )
    match_status = _classify_transaction(
        counterpart_identity,
        _build_existing_map(config, peer_import_account_id, located.journal_path),
    )
    if match_status == "duplicate":
        raise ValueError("A matching destination-side transaction already exists, so this transfer cannot be resolved manually.")
    if match_status == "conflict":
        raise ValueError(
            "The destination-side import identity already exists with different details, so this transfer cannot be resolved manually."
        )

    peer_import_account = config.import_accounts.get(peer_import_account_id)
    if peer_import_account is None:
        raise ValueError("The destination import account is no longer configured.")
    import_source = import_source_summary(config, peer_import_account)
    institution_template = str(
        import_source.get("institution_id") or import_source.get("profile_id") or "custom_csv"
    ).strip()

    counterpart_updates = {
        **build_import_match_transfer_metadata_updates(
            transfer_id=token["transferId"],
            peer_account_id=source_tracked_account_id,
            transfer_match_state=TRANSFER_MATCH_STATE_MATCHED,
        ),
        "import_account_id": peer_import_account_id,
        "institution_template": institution_template,
        "source_identity": counterpart_identity["sourceIdentity"],
        "source_payload_hash": counterpart_identity["sourcePayloadHash"],
        "importer_version": IMPORTER_VERSION,
        MANUAL_TRANSFER_RESOLUTION_METADATA_KEY: MANUAL_TRANSFER_RESOLUTION_METADATA_VALUE,
    }
    source_updates = {
        **build_import_match_transfer_metadata_updates(
            transfer_id=token["transferId"],
            peer_account_id=token["peerAccountId"],
            transfer_match_state=TRANSFER_MATCH_STATE_MATCHED,
        ),
        MANUAL_TRANSFER_RESOLUTION_METADATA_KEY: MANUAL_TRANSFER_RESOLUTION_METADATA_VALUE,
    }

    counterpart_lines = upsert_transaction_metadata(counterpart_core_lines, counterpart_updates)
    source_updated_lines = upsert_transaction_metadata(located.block_lines, source_updates)

    absolute_amount = abs(source_amount)
    if source_amount < 0:
        from_account_id = source_tracked_account_id
        from_account_name = source_account_name
        to_account_id = token["peerAccountId"]
        to_account_name = peer_account_name
    else:
        from_account_id = token["peerAccountId"]
        from_account_name = peer_account_name
        to_account_id = source_tracked_account_id
        to_account_name = source_account_name

    return ManualTransferResolutionPlan(
        resolution_token=resolution_token,
        journal_path=located.journal_path,
        journal_preamble_lines=located.preamble_lines,
        journal_transaction_blocks=located.transaction_blocks,
        source_block_index=located.block_index,
        source_updated_lines=source_updated_lines,
        counterpart_lines=counterpart_lines,
        counterpart_source_identity=counterpart_identity["sourceIdentity"],
        counterpart_source_payload_hash=counterpart_identity["sourcePayloadHash"],
        peer_import_account_id=peer_import_account_id,
        amount=absolute_amount,
        posted_on=parsed_source.posted_on.isoformat(),
        payee=parsed_source.payee,
        from_account_id=from_account_id,
        from_account_name=from_account_name,
        to_account_id=to_account_id,
        to_account_name=to_account_name,
        source_account_id=source_tracked_account_id,
        source_account_name=source_account_name,
        destination_account_id=token["peerAccountId"],
        destination_account_name=peer_account_name,
    )


def preview_manual_transfer_resolution(config: AppConfig, resolution_token: str) -> dict:
    plan = _build_resolution_plan(config, resolution_token)
    return {
        "resolutionToken": plan.resolution_token,
        "date": plan.posted_on,
        "payee": plan.payee,
        "amount": amount_to_number(plan.amount),
        "baseCurrency": str(config.workspace.get("base_currency", "USD")),
        "sourceAccountId": plan.source_account_id,
        "sourceAccountName": plan.source_account_name,
        "destinationAccountId": plan.destination_account_id,
        "destinationAccountName": plan.destination_account_name,
        "fromAccountId": plan.from_account_id,
        "fromAccountName": plan.from_account_name,
        "toAccountId": plan.to_account_id,
        "toAccountName": plan.to_account_name,
        "warning": RESOLUTION_WARNING,
    }


def apply_manual_transfer_resolution(config: AppConfig, resolution_token: str) -> dict:
    plan = _build_resolution_plan(config, resolution_token)

    updated_blocks = list(plan.journal_transaction_blocks)
    updated_blocks[plan.source_block_index] = plan.source_updated_lines
    merged_blocks = _merge_transaction_blocks(updated_blocks, [plan.counterpart_lines])
    rendered = _render_journal_text(plan.journal_preamble_lines, merged_blocks)
    backup_path = backup_file(plan.journal_path, "manual-transfer-resolution")
    plan.journal_path.write_text(rendered, encoding="utf-8")

    return {
        "applied": True,
        "backupPath": str(backup_path.resolve()),
        "journalPath": str(plan.journal_path.resolve()),
        "date": plan.posted_on,
        "payee": plan.payee,
        "amount": amount_to_number(plan.amount),
        "sourceAccountId": plan.source_account_id,
        "sourceAccountName": plan.source_account_name,
        "destinationAccountId": plan.destination_account_id,
        "destinationAccountName": plan.destination_account_name,
    }
