from __future__ import annotations

import argparse
import os
import json
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from services import journal_writer
from services.config_service import AppConfig, load_config
from services.currency_parser import parse_amount
from services.journal_migration_service import migrate_lf_metadata
from services.manual_entry_service import build_manual_transaction_block, create_manual_transaction


DEFAULT_API_URL = "http://127.0.0.1:8000"


def _find_tracked_account(config: AppConfig, ledger_account: str) -> tuple[str, dict]:
    target = ledger_account.strip()
    for account_id, account_cfg in config.tracked_accounts.items():
        if str(account_cfg.get("ledger_account", "")).strip() == target:
            return account_id, account_cfg
    raise ValueError(f"Tracked account not found for Ledger account: {ledger_account}")


def _add_transaction(args: argparse.Namespace) -> dict:
    config = load_config(Path(args.config))
    tracked_account_id, tracked_account_cfg = _find_tracked_account(config, args.from_account)
    year = args.date[:4]
    journal_path = config.journal_dir / f"{year}.journal"
    accounts_dat = config.init_dir / "10-accounts.dat"
    currency = str(config.workspace.get("base_currency", "USD"))

    if args.dry_run:
        block = build_manual_transaction_block(
            txn_date=args.date,
            payee=args.payee,
            amount=parse_amount(args.amount),
            destination_account=args.to_account,
            tracked_ledger_account=args.from_account,
            currency=currency,
        )
        return {
            "created": False,
            "dryRun": True,
            "journalPath": str(journal_path),
            "block": block,
            "trackedAccountId": tracked_account_id,
        }

    with journal_writer.mutate(
        config=config,
        paths=[journal_path],
        tag="manual-entry",
        event_type="manual_entry.created.v1",
    ) as mut:
        result = create_manual_transaction(
            config=config,
            journal_path=journal_path,
            accounts_dat=accounts_dat,
            tracked_account_cfg=tracked_account_cfg,
            txn_date=args.date,
            payee=args.payee,
            amount_str=args.amount,
            destination_account=args.to_account,
            currency=currency,
        )
        mut.summary = f"Created manual entry: {args.payee or '(no payee)'} {args.amount} {currency}"
        mut.payload = {
            "date": args.date,
            "payee": args.payee or "",
            "amount": args.amount,
            "currency": currency,
            "destination_account": args.to_account,
            "source_account": args.from_account,
            "tracked_account_id": tracked_account_id,
            "source": args.source,
        }

    return {**result, "eventId": mut.event_id}


def _migrate_lf_metadata(args: argparse.Namespace) -> dict:
    config = load_config(Path(args.config))
    return migrate_lf_metadata(config)


def _run_server(args: argparse.Namespace) -> dict:
    workspace = Path(args.workspace).expanduser().resolve()
    os.environ["LEDGER_FLOW_ROOT"] = str(workspace)
    result = {
        "host": args.host,
        "port": args.port,
        "reload": args.reload,
        "workspace": str(workspace),
    }
    print(json.dumps(result, sort_keys=True), flush=True)

    import uvicorn

    uvicorn.run(
        "main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return None


def _normalize_cli_date(raw: str | None) -> str:
    if raw is None:
        return date.today().isoformat()
    value = raw.strip().lower()
    if value == "today":
        return date.today().isoformat()
    if value == "yesterday":
        return (date.today() - timedelta(days=1)).isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError(f"Invalid date: {raw}") from exc


def _validate_positive_amount(raw: str) -> str:
    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("Amount must be a positive decimal.") from exc
    if amount <= 0:
        raise ValueError("Amount must be a positive decimal.")
    return raw


def _resolve_api_url(args: argparse.Namespace) -> str:
    return (args.api_url or os.environ.get("LEDGER_FLOW_API_URL") or DEFAULT_API_URL).rstrip("/")


def _transactions_create(args: argparse.Namespace) -> dict | None:
    payload = {
        "sourceAccount": args.account,
        "date": _normalize_cli_date(args.date),
        "payee": args.payee,
        "amount": _validate_positive_amount(args.amount),
    }
    if args.to_account is not None:
        payload["destinationAccount"] = args.to_account
    if args.note is not None:
        payload["notes"] = args.note

    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{_resolve_api_url(args)}/api/transactions/create",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        response_payload = json.loads(response.read().decode("utf-8"))
    if args.json:
        return response_payload
    return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ledger-flow")
    parser.add_argument(
        "--config",
        default="settings/workspace.toml",
        help="Path to workspace.toml. Defaults to settings/workspace.toml in the current directory.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    add = subparsers.add_parser("add", help="Create a manual transaction")
    add.add_argument("--payee", required=True)
    add.add_argument("--amount", required=True)
    add.add_argument("--date", required=True)
    add.add_argument("--to", dest="to_account", required=True)
    add.add_argument("--from", dest="from_account", required=True)
    add.add_argument("--source", default="cli")
    add.add_argument("--dry-run", action="store_true")
    add.set_defaults(handler=_add_transaction)

    migrate = subparsers.add_parser(
        "migrate-lf-metadata",
        help="One-time migration: assign lf_txn_id and rename app metadata keys to lf_ house style",
    )
    migrate.set_defaults(handler=_migrate_lf_metadata)

    server = subparsers.add_parser("server", help="Start the Ledger Flow API server")
    server.add_argument(
        "--workspace",
        default=".",
        help="Workspace root. Defaults to the current directory.",
    )
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8000)
    server.add_argument("--reload", action="store_true")
    server.set_defaults(handler=_run_server)

    transactions = subparsers.add_parser("transactions", help="Transaction commands")
    transaction_subparsers = transactions.add_subparsers(dest="transaction_command", required=True)
    create = transaction_subparsers.add_parser("create", help="Create a manual transaction through the API")
    create.add_argument("--api-url")
    create.add_argument("--account", required=True)
    create.add_argument(
        "--to",
        dest="to_account",
        help="Destination posting account for the manual transaction.",
    )
    create.add_argument("--payee", required=True)
    create.add_argument("--amount", required=True)
    create.add_argument("--date")
    create.add_argument("--note")
    create.add_argument("--json", action="store_true")
    create.set_defaults(handler=_transactions_create)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.handler(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except urllib.error.HTTPError as exc:
        message = f"API request failed: HTTP {exc.code}"
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("detail")
            if isinstance(detail, str) and detail:
                message = detail
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            pass
        print(message, file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"API request failed: {exc.reason}", file=sys.stderr)
        return 1
    if result is not None:
        print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
