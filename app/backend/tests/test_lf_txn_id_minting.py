"""App-created blocks mint ``lf_txn_id`` at write time (#17, TASK decision 8).

Every writer that creates a new transaction block — manual entry, import
apply, reconciliation assertion (covered in test_reconciliation_service),
opening balance — records a durable identity directly after the header so
the block stays targetable after later edits move it. Without this, new
blocks get ephemeral projected ids that change on the next content shift.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from services.config_service import AppConfig
from services.import_service import apply_import
from services.manual_entry_service import (
    build_manual_transaction_block,
    create_manual_transaction,
)
from services.opening_balance_service import write_opening_balance

LF_TXN_ID_RE = re.compile(r"^    ; lf_txn_id: (txn_[0-9a-f]{32})$")


def _make_config(workspace: Path) -> AppConfig:
    for rel in ["settings", "journals", "inbox", "rules", "opening", "imports"]:
        (workspace / rel).mkdir(parents=True, exist_ok=True)
    return AppConfig(
        root_dir=workspace,
        config_toml=workspace / "settings" / "workspace.toml",
        workspace={"name": "Test", "start_year": 2026, "base_currency": "USD"},
        dirs={
            "csv_dir": "inbox",
            "journal_dir": "journals",
            "init_dir": "rules",
            "opening_bal_dir": "opening",
            "imports_dir": "imports",
        },
        institution_templates={},
        import_accounts={},
        tracked_accounts={},
    )


class TestManualEntryMinting:
    def test_block_carries_lf_txn_id_after_header(self) -> None:
        block = build_manual_transaction_block(
            txn_date="2026-03-15",
            payee="Coffee",
            amount=Decimal("4.50"),
            destination_account="Expenses:Coffee",
            tracked_ledger_account="Assets:Checking",
        )
        assert LF_TXN_ID_RE.match(block[1]), block

    def test_two_blocks_mint_distinct_ids(self) -> None:
        ids = set()
        for _ in range(2):
            block = build_manual_transaction_block(
                txn_date="2026-03-15",
                payee="Coffee",
                amount=Decimal("4.50"),
                destination_account="Expenses:Coffee",
                tracked_ledger_account="Assets:Checking",
            )
            ids.add(block[1])
        assert len(ids) == 2

    def test_created_journal_entry_carries_id(self, tmp_path: Path) -> None:
        journal = tmp_path / "journals" / "2026.journal"
        accounts_dat = tmp_path / "rules" / "10-accounts.dat"
        accounts_dat.parent.mkdir(parents=True)
        accounts_dat.write_text("account Expenses:Coffee\n", encoding="utf-8")

        create_manual_transaction(
            journal_path=journal,
            accounts_dat=accounts_dat,
            tracked_account_cfg={"ledger_account": "Assets:Checking"},
            txn_date="2026-03-15",
            payee="Coffee",
            amount_str="4.50",
            destination_account="Expenses:Coffee",
        )

        lines = journal.read_text(encoding="utf-8").splitlines()
        header_idx = next(i for i, l in enumerate(lines) if l.startswith("2026-03-15"))
        assert LF_TXN_ID_RE.match(lines[header_idx + 1]), lines


class TestImportApplyMinting:
    def test_new_rows_gain_ids_existing_blocks_untouched(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path / "workspace")
        target = config.journal_dir / "2026.journal"
        existing = (
            "2026-01-05 Existing\n"
            "    ; lf_txn_id: txn_existing\n"
            "    Assets:Checking  $-1.00\n"
            "    Expenses:Unknown\n"
        )
        target.write_text(existing, encoding="utf-8")

        stage = {
            "targetJournalPath": str(target),
            "importAccountId": "checking",
            "year": "2026",
            "sourceFileSha256": "deadbeef",
            "destinationAccount": "Assets:Checking",
            "preparedTransactions": [
                {
                    "matchStatus": "new",
                    "annotatedRaw": (
                        "2026-02-01 Coffee Shop\n"
                        "    ; lf_source_identity: src-1\n"
                        "    Assets:Checking  $-7.50\n"
                        "    Expenses:Unknown\n"
                    ),
                    "sourceIdentity": "src-1",
                    "sourcePayloadHash": "payload-1",
                    "date": "2026-02-01",
                    "payee": "Coffee Shop",
                },
            ],
        }

        _, appended, _, _ = apply_import(config, stage)
        assert appended == 1

        text = target.read_text(encoding="utf-8")
        # Existing block byte-identical (still exactly one lf_txn_id line).
        assert existing.rstrip("\n") in text
        # New block minted an id directly after its header.
        lines = text.splitlines()
        header_idx = next(i for i, l in enumerate(lines) if "Coffee Shop" in l)
        assert LF_TXN_ID_RE.match(lines[header_idx + 1]), lines
        assert lines[header_idx + 1] != "    ; lf_txn_id: txn_existing"


class TestOpeningBalanceMinting:
    def test_written_block_carries_id(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path / "workspace")

        write_opening_balance(config, "checking", "Assets:Checking", "100.00")

        lines = (
            (config.opening_bal_dir / "checking.journal")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        assert LF_TXN_ID_RE.match(lines[1]), lines

    def test_rewrite_preserves_existing_id(self, tmp_path: Path) -> None:
        """Opening balance writes are upserts — the block's identity must
        survive an amount edit."""
        config = _make_config(tmp_path / "workspace")
        path = config.opening_bal_dir / "checking.journal"

        write_opening_balance(config, "checking", "Assets:Checking", "100.00")
        first_id_line = path.read_text(encoding="utf-8").splitlines()[1]

        write_opening_balance(config, "checking", "Assets:Checking", "250.00")
        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines[1] == first_id_line
        assert "250.00" in "\n".join(lines)
