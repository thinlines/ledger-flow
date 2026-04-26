"""Tests for reconciliation_service — assertion writer, fence lookup, failure detection."""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from services import event_log_service
from services.config_service import AppConfig
from services.event_log_service import EVENTS_FILENAME, emit_event
from services.import_service import apply_reconciliation_fence
from services.reconciliation_service import (
    AssertionFailure,
    _parse_all_assertion_failures,
    _parse_ledger_assertion_failure,
    latest_reconciliation_date,
    latest_reconciliation_dates_by_tracked_id,
    parse_closing_balance,
    reconciliation_status,
    restore_from_backup,
    verify_assertion,
    write_assertion_transaction,
)


@pytest.fixture(autouse=True)
def _clear_hash_cache():
    event_log_service._hash_cache.clear()
    yield
    event_log_service._hash_cache.clear()


def _make_config(workspace: Path) -> AppConfig:
    for rel in ["settings", "journals", "inbox", "rules", "opening", "imports"]:
        (workspace / rel).mkdir(parents=True, exist_ok=True)

    return AppConfig(
        root_dir=workspace,
        config_toml=workspace / "settings" / "workspace.toml",
        workspace={"name": "Test Books", "start_year": 2026, "base_currency": "USD"},
        dirs={
            "csv_dir": "inbox",
            "journal_dir": "journals",
            "init_dir": "rules",
            "opening_bal_dir": "opening",
            "imports_dir": "imports",
        },
        institution_templates={},
        import_accounts={
            "checking": {
                "display_name": "Wells Fargo Checking",
                "ledger_account": "Assets:Checking:Wells Fargo",
                "tracked_account_id": "checking",
            },
        },
        tracked_accounts={
            "checking": {
                "display_name": "Wells Fargo Checking",
                "ledger_account": "Assets:Checking:Wells Fargo",
                "import_account_id": "checking",
            },
            "savings": {
                "display_name": "Savings",
                "ledger_account": "Assets:Savings",
                "import_account_id": None,
            },
        },
        payee_aliases="payee_aliases.csv",
    )


def _seed_journal(config: AppConfig, body: str = "") -> Path:
    journal = config.journal_dir / "2026.journal"
    journal.write_text(body, encoding="utf-8")
    return journal


def _seed_accounts_dat(config: AppConfig) -> None:
    """Declare all tracked ledger accounts so ledger --strict has no warnings."""
    lines = [
        "account Assets:Checking:Wells Fargo",
        "account Assets:Savings",
        "account Equity:Opening-Balances",
    ]
    (config.init_dir / "10-accounts.dat").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _opening_balance_block(account: str, amount: str, opening_date: str = "2026-01-01") -> str:
    return (
        f"{opening_date} * Opening Balance\n"
        f"    {account}  {amount}\n"
        f"    Equity:Opening-Balances\n"
    )


# ---------------------------------------------------------------------------
# parse_closing_balance
# ---------------------------------------------------------------------------


class TestParseClosingBalance:
    def test_plain_number(self) -> None:
        assert parse_closing_balance("2500.00") == Decimal("2500.00")

    def test_dollar_sign_and_commas(self) -> None:
        assert parse_closing_balance("$2,500.00") == Decimal("2500.00")

    def test_negative(self) -> None:
        assert parse_closing_balance("-100.00") == Decimal("-100.00")

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_closing_balance("not-a-number")

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_closing_balance("")


# ---------------------------------------------------------------------------
# Writer ordering invariant
# ---------------------------------------------------------------------------


class TestWriterOrdering:
    def test_inserts_after_other_transactions_on_same_date(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path / "workspace")
        body = (
            "2026-04-17 Coffee\n"
            "    Expenses:Food  $5.00\n"
            "    Assets:Checking:Wells Fargo\n"
            "\n"
            "2026-04-17 Lunch\n"
            "    Expenses:Food  $12.00\n"
            "    Assets:Checking:Wells Fargo\n"
        )
        journal = _seed_journal(config, body)

        result, _ = write_assertion_transaction(
            config=config,
            tracked_account_cfg=config.tracked_accounts["checking"],
            period_start=date(2026, 3, 18),
            period_end=date(2026, 4, 17),
            closing_balance=Decimal("2500.00"),
            currency="USD",
            event_id="recon-evt-1",
        )

        text = journal.read_text(encoding="utf-8")
        # The reconciliation header should appear AFTER both coffee and lunch.
        coffee_idx = text.index("Coffee")
        lunch_idx = text.index("Lunch")
        recon_idx = text.index("Statement reconciliation")
        assert coffee_idx < lunch_idx < recon_idx

        # The reconciliation transaction is the last transaction with date 2026-04-17.
        lines = text.splitlines()
        last_april17_header = None
        for i, line in enumerate(lines):
            if line.startswith("2026-04-17"):
                last_april17_header = i
        assert last_april17_header is not None
        assert "Statement reconciliation" in lines[last_april17_header]
        assert result.line_number == last_april17_header

    def test_inserts_after_later_same_date_transaction(self, tmp_path: Path) -> None:
        """Critical invariant: even if another transaction on periodEnd lives later in
        the file, the assertion still becomes the last one for that date."""
        config = _make_config(tmp_path / "workspace")
        body = (
            "2026-04-17 First\n"
            "    Expenses:Food  $5.00\n"
            "    Assets:Checking:Wells Fargo\n"
            "\n"
            "2026-04-18 NextDay\n"
            "    Expenses:Food  $7.00\n"
            "    Assets:Checking:Wells Fargo\n"
            "\n"
            "2026-04-17 LaterSameDate\n"
            "    Expenses:Food  $9.00\n"
            "    Assets:Checking:Wells Fargo\n"
        )
        journal = _seed_journal(config, body)

        write_assertion_transaction(
            config=config,
            tracked_account_cfg=config.tracked_accounts["checking"],
            period_start=date(2026, 3, 18),
            period_end=date(2026, 4, 17),
            closing_balance=Decimal("2500.00"),
            currency="USD",
            event_id="recon-evt-2",
        )

        text = journal.read_text(encoding="utf-8")
        # Find each header.
        first_idx = text.index("First")
        later_idx = text.index("LaterSameDate")
        recon_idx = text.index("Statement reconciliation")
        assert first_idx < later_idx < recon_idx

    def test_inserts_at_top_when_period_end_precedes_all(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path / "workspace")
        body = (
            "2026-05-01 Future\n"
            "    Expenses:Food  $5.00\n"
            "    Assets:Checking:Wells Fargo\n"
        )
        journal = _seed_journal(config, body)

        result, _ = write_assertion_transaction(
            config=config,
            tracked_account_cfg=config.tracked_accounts["checking"],
            period_start=date(2026, 3, 18),
            period_end=date(2026, 4, 17),
            closing_balance=Decimal("2500.00"),
            currency="USD",
            event_id="recon-evt-3",
        )

        text = journal.read_text(encoding="utf-8")
        recon_idx = text.index("Statement reconciliation")
        future_idx = text.index("Future")
        assert recon_idx < future_idx
        assert result.line_number == 0

    def test_creates_journal_when_year_file_missing(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path / "workspace")
        journal_path = config.journal_dir / "2026.journal"
        assert not journal_path.exists()

        result, _ = write_assertion_transaction(
            config=config,
            tracked_account_cfg=config.tracked_accounts["checking"],
            period_start=date(2026, 3, 18),
            period_end=date(2026, 4, 17),
            closing_balance=Decimal("2500.00"),
            currency="USD",
            event_id="recon-evt-4",
        )

        assert journal_path.exists()
        text = journal_path.read_text(encoding="utf-8")
        assert "Statement reconciliation" in text
        assert "    ; reconciliation_event_id: recon-evt-4" in text
        assert "    ; statement_period: 2026-03-18..2026-04-17" in text
        assert "Assets:Checking:Wells Fargo  $0 = $2,500.00" in text
        assert result.header_line.startswith("2026-04-17 * Statement reconciliation")

    def test_inserts_after_earlier_date_when_no_period_end_match(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path / "workspace")
        body = (
            "2026-04-10 Earlier\n"
            "    Expenses:Food  $5.00\n"
            "    Assets:Checking:Wells Fargo\n"
            "\n"
            "2026-04-25 Later\n"
            "    Expenses:Food  $7.00\n"
            "    Assets:Checking:Wells Fargo\n"
        )
        journal = _seed_journal(config, body)

        write_assertion_transaction(
            config=config,
            tracked_account_cfg=config.tracked_accounts["checking"],
            period_start=date(2026, 3, 18),
            period_end=date(2026, 4, 17),
            closing_balance=Decimal("2500.00"),
            currency="USD",
            event_id="recon-evt-5",
        )

        text = journal.read_text(encoding="utf-8")
        earlier_idx = text.index("Earlier")
        recon_idx = text.index("Statement reconciliation")
        later_idx = text.index("Later")
        assert earlier_idx < recon_idx < later_idx


# ---------------------------------------------------------------------------
# Verification + rollback (real ledger)
# ---------------------------------------------------------------------------


class TestVerifyAndRollback:
    def test_passes_when_balance_matches(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        _seed_journal(
            config,
            _opening_balance_block("Assets:Checking:Wells Fargo", "$100.00")
            + "\n"
            + "2026-03-15 Deposit\n"
            + "    Assets:Checking:Wells Fargo  $400.00\n"
            + "    Equity:Opening-Balances\n",
        )

        write_assertion_transaction(
            config=config,
            tracked_account_cfg=config.tracked_accounts["checking"],
            period_start=date(2026, 3, 18),
            period_end=date(2026, 4, 17),
            closing_balance=Decimal("500.00"),
            currency="USD",
            event_id="recon-pass",
        )

        failure = verify_assertion(config)
        assert failure is None

    def test_fails_with_parsed_expected_and_actual_when_balance_wrong(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        _seed_journal(
            config,
            _opening_balance_block("Assets:Checking:Wells Fargo", "$100.00"),
        )

        write_assertion_transaction(
            config=config,
            tracked_account_cfg=config.tracked_accounts["checking"],
            period_start=date(2026, 3, 18),
            period_end=date(2026, 4, 17),
            closing_balance=Decimal("250.00"),
            currency="USD",
            event_id="recon-fail",
        )

        failure = verify_assertion(config)
        assert failure is not None
        assert failure.expected is not None
        assert failure.actual is not None
        # Expected is the user-supplied balance ($250.00); actual is journal-derived ($100.00).
        assert "250" in failure.expected.replace(",", "")
        assert "100" in failure.actual.replace(",", "")
        assert "Balance assertion off by" in failure.raw_error


# ---------------------------------------------------------------------------
# Rollback preserves byte-equivalence (round-trip via restore_from_backup)
# ---------------------------------------------------------------------------


class TestRollback:
    def test_restore_from_backup_yields_byte_identical_journal(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path / "workspace")
        body = (
            "2026-04-10 Earlier\n"
            "    Expenses:Food  $5.00\n"
            "    Assets:Checking:Wells Fargo\n"
        )
        journal = _seed_journal(config, body)
        before_bytes = journal.read_bytes()

        _, backup = write_assertion_transaction(
            config=config,
            tracked_account_cfg=config.tracked_accounts["checking"],
            period_start=date(2026, 3, 18),
            period_end=date(2026, 4, 17),
            closing_balance=Decimal("2500.00"),
            currency="USD",
            event_id="recon-rollback",
        )

        # The journal was mutated.
        assert journal.read_bytes() != before_bytes
        # Backup matches the pre-write content.
        assert backup.read_bytes() == before_bytes

        restore_from_backup(journal, backup)
        assert journal.read_bytes() == before_bytes


# ---------------------------------------------------------------------------
# latest_reconciliation_date / fence lookup
# ---------------------------------------------------------------------------


class TestLatestReconciliationDate:
    def test_returns_none_when_no_assertions(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_journal(config, "")
        assert latest_reconciliation_date(config, "Assets:Checking:Wells Fargo") is None

    def test_returns_most_recent_for_account(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_journal(
            config,
            "2026-03-31 * Statement reconciliation · checking · ending 2026-03-31\n"
            "    ; reconciliation_event_id: e1\n"
            "    ; statement_period: 2026-03-01..2026-03-31\n"
            "    Assets:Checking:Wells Fargo  $0 = $100.00\n"
            "\n"
            "2026-04-30 * Statement reconciliation · checking · ending 2026-04-30\n"
            "    ; reconciliation_event_id: e2\n"
            "    ; statement_period: 2026-04-01..2026-04-30\n"
            "    Assets:Checking:Wells Fargo  $0 = $200.00\n",
        )
        result = latest_reconciliation_date(config, "Assets:Checking:Wells Fargo")
        assert result == date(2026, 4, 30)

    def test_excludes_handwritten_assertions(self, tmp_path: Path) -> None:
        """Hand-written assertions (no reconciliation_event_id) are honored for failure
        detection but excluded from the fence."""
        config = _make_config(tmp_path / "workspace")
        _seed_journal(
            config,
            "2026-04-30 Verify by hand\n"
            "    Assets:Checking:Wells Fargo  $0 = $200.00\n",
        )
        assert latest_reconciliation_date(config, "Assets:Checking:Wells Fargo") is None

    def test_overlapping_account_hierarchy_matches_exact(self, tmp_path: Path) -> None:
        """Parent and child accounts must not collide — match the exact ledger account."""
        config = _make_config(tmp_path / "workspace")
        # Add a parent tracked account that shares a prefix.
        config.tracked_accounts["parent"] = {
            "display_name": "Checking parent",
            "ledger_account": "Assets:Checking",
            "import_account_id": None,
        }
        _seed_journal(
            config,
            "2026-04-30 * Statement reconciliation · child\n"
            "    ; reconciliation_event_id: e1\n"
            "    ; statement_period: 2026-04-01..2026-04-30\n"
            "    Assets:Checking:Wells Fargo  $0 = $200.00\n",
        )
        assert latest_reconciliation_date(config, "Assets:Checking:Wells Fargo") == date(2026, 4, 30)
        assert latest_reconciliation_date(config, "Assets:Checking") is None


# ---------------------------------------------------------------------------
# Import fence helper
# ---------------------------------------------------------------------------


class TestApplyReconciliationFence:
    def _row(self, date_str: str, status: str = "new", source_id: str = "x") -> dict:
        return {"date": date_str, "matchStatus": status, "sourceIdentity": source_id}

    def test_row_on_reconciliation_date_becomes_conflict(self) -> None:
        rows = [self._row("2026-04-17")]
        apply_reconciliation_fence(
            rows, tracked_account_id="checking", latest_dates={"checking": date(2026, 4, 17)}
        )
        assert rows[0]["matchStatus"] == "conflict"
        assert rows[0]["conflictReason"] == "reconciled_date_fence"
        assert rows[0]["reconciledThrough"] == "2026-04-17"

    def test_row_after_reconciliation_date_unchanged(self) -> None:
        rows = [self._row("2026-04-18")]
        apply_reconciliation_fence(
            rows, tracked_account_id="checking", latest_dates={"checking": date(2026, 4, 17)}
        )
        assert rows[0]["matchStatus"] == "new"
        assert rows[0]["conflictReason"] is None
        assert rows[0]["reconciledThrough"] is None

    def test_existing_conflict_keeps_identity_collision_reason(self) -> None:
        rows = [self._row("2026-04-30", status="conflict")]
        apply_reconciliation_fence(
            rows, tracked_account_id="checking", latest_dates={"checking": date(2026, 4, 17)}
        )
        assert rows[0]["matchStatus"] == "conflict"
        assert rows[0]["conflictReason"] == "identity_collision"
        assert rows[0]["reconciledThrough"] is None

    def test_orphan_import_skips_fence(self) -> None:
        rows = [self._row("2026-04-17")]
        apply_reconciliation_fence(
            rows, tracked_account_id=None, latest_dates={"checking": date(2026, 4, 17)}
        )
        assert rows[0]["matchStatus"] == "new"
        assert rows[0]["conflictReason"] is None
        assert rows[0]["reconciledThrough"] is None

    def test_no_reconciliation_date_leaves_rows_alone(self) -> None:
        rows = [self._row("2026-04-17")]
        apply_reconciliation_fence(
            rows, tracked_account_id="checking", latest_dates={}
        )
        assert rows[0]["matchStatus"] == "new"
        assert rows[0]["conflictReason"] is None

    def test_latest_dates_by_tracked_id_drives_fence_via_real_journal(self, tmp_path: Path) -> None:
        """End-to-end: write a reconciliation, then verify the per-tracked-id lookup
        function returns a dict the fence helper can consume."""
        config = _make_config(tmp_path / "workspace")
        _seed_journal(
            config,
            "2026-04-17 * Statement reconciliation · checking · ending 2026-04-17\n"
            "    ; reconciliation_event_id: e1\n"
            "    ; statement_period: 2026-03-18..2026-04-17\n"
            "    Assets:Checking:Wells Fargo  $0 = $200.00\n",
        )

        latest = latest_reconciliation_dates_by_tracked_id(config)
        assert latest == {"checking": date(2026, 4, 17)}

        rows = [
            {"date": "2026-04-17", "matchStatus": "new", "sourceIdentity": "row-on-fence"},
            {"date": "2026-04-18", "matchStatus": "new", "sourceIdentity": "row-day-after"},
        ]
        apply_reconciliation_fence(rows, tracked_account_id="checking", latest_dates=latest)

        assert rows[0]["matchStatus"] == "conflict"
        assert rows[0]["conflictReason"] == "reconciled_date_fence"
        assert rows[0]["reconciledThrough"] == "2026-04-17"
        assert rows[1]["matchStatus"] == "new"
        assert rows[1]["conflictReason"] is None
        assert rows[1]["reconciledThrough"] is None


# ---------------------------------------------------------------------------
# Failure-detection translation (fixture stderr snapshot)
# ---------------------------------------------------------------------------


# Captured from a real `ledger -f <journal> bal --strict` run on a journal with
# a reconciliation transaction whose asserted balance does not match.  This is
# the exact byte form the parser must handle.
LEDGER_ASSERTION_FAILURE_FIXTURE = """\
While parsing file "/tmp/workspace/journals/2026.journal", line 9:
While parsing posting:
  Assets:Checking  $0 = $50.00
                        ^^^^^^
Error: Balance assertion off by $-50.00 (expected to see $100.00)
"""


class TestFailureDetectionTranslation:
    def test_parse_single_failure_recovers_expected_and_actual(self) -> None:
        failure = _parse_ledger_assertion_failure(LEDGER_ASSERTION_FAILURE_FIXTURE)
        assert failure is not None
        # Ledger's "expected to see" is journal-derived (our actual).
        assert "100.00" in failure.actual
        # User's assertion (our expected) recovered as actual + off = $100 + (-$50) = $50.
        assert "50.00" in failure.expected
        assert failure.file == "/tmp/workspace/journals/2026.journal"
        assert failure.line == 9
        assert "Balance assertion off by" in failure.raw_error

    def test_parse_returns_none_for_non_assertion_error(self) -> None:
        assert _parse_ledger_assertion_failure("Error: unrelated parse failure") is None

    def test_parse_all_assertion_failures_handles_multiple(self) -> None:
        text = LEDGER_ASSERTION_FAILURE_FIXTURE + LEDGER_ASSERTION_FAILURE_FIXTURE
        failures = _parse_all_assertion_failures(text)
        assert len(failures) == 2


# ---------------------------------------------------------------------------
# reconciliation_status: full round-trip with a real broken journal
# ---------------------------------------------------------------------------


class TestReconciliationStatus:
    def test_healthy_journal_reports_ok_for_all_accounts(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        _seed_journal(
            config,
            _opening_balance_block("Assets:Checking:Wells Fargo", "$100.00"),
        )
        status = reconciliation_status(config)
        assert status == {"checking": {"ok": True}, "savings": {"ok": True}}

    def test_broken_assertion_surfaces_on_correct_tracked_account(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        _seed_journal(
            config,
            _opening_balance_block("Assets:Checking:Wells Fargo", "$100.00")
            + "\n"
            + "2026-04-17 * Statement reconciliation · Wells Fargo · ending 2026-04-17\n"
            "    ; reconciliation_event_id: e1\n"
            "    ; statement_period: 2026-03-18..2026-04-17\n"
            "    Assets:Checking:Wells Fargo  $0 = $200.00\n",
        )

        status = reconciliation_status(config)
        assert status["savings"] == {"ok": True}
        assert status["checking"]["ok"] is False
        broken = status["checking"]["broken"]
        assert "200" in (broken["expected"] or "").replace(",", "")
        assert "100" in (broken["actual"] or "").replace(",", "")
        assert "Balance assertion off by" in broken["rawError"]
        assert broken["date"] == "2026-04-17"


# ---------------------------------------------------------------------------
# Integration: writer + emit_event share the same id
# ---------------------------------------------------------------------------


class TestEventIdLinkage:
    def test_emit_event_accepts_caller_supplied_id(self, tmp_path: Path) -> None:
        from services.event_log_service import emit_event as ee

        eid = "01HGECUSTOMID00000000000000"
        returned = ee(
            tmp_path,
            event_type="account.reconciled.v1",
            summary="Test",
            payload={"x": 1},
            journal_refs=[],
            event_id=eid,
        )
        assert returned == eid

        events = (tmp_path / EVENTS_FILENAME).read_text().splitlines()
        parsed = json.loads(events[0])
        assert parsed["id"] == eid
