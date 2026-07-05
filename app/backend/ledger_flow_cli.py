from __future__ import annotations

import argparse
import os
import json
import sys
from pathlib import Path

from services import journal_writer
from services.config_service import AppConfig, load_config
from services.currency_parser import parse_amount
from services.journal_migration_service import migrate_lf_metadata
from services.manual_entry_service import build_manual_transaction_block, create_manual_transaction


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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.handler(args)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    if result is not None:
        print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
