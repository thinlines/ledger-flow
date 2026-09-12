"""The transaction edit session, driven through its public interface.

Every test runs a real temporary workspace and asserts on what is externally
observable: the journal text (byte-exact, including untouched lines and the
trailing newline), the projected row, and the recorded operation. Nothing
here reaches for line indices, the posting codec, or the journal-file layer.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from conftest import read_operation_events
from services.config_service import AppConfig
from services.header_parser import TransactionStatus
from services.projection_db import database_path
from services.projection_service import refresh_projection
from services.transaction_edit_service import (
    AccountChange,
    ActionConflict,
    AlreadyInState,
    EditError,
    MatchRestoration,
    NotACategory,
    NotTracked,
    SplitTransaction,
    StaleTransaction,
    TransactionNotFound,
    edit,
)
from services.undo_service import UndoOutcome, undo_event

JOURNAL = """\
2026-03-15 * Whole Foods
    ; lf_txn_id: txn_wf
    Assets:Bank:Checking  USD -50.00
    Expenses:Groceries  USD 50.00

2026-03-20 Target
    ; lf_txn_id: txn_target
    Assets:Bank:Checking  $-30.00
    Expenses:Unknown  $30.00

2026-03-22 * Move money
    ; lf_txn_id: txn_transfer
    Assets:Bank:Checking  $-100.00
    Assets:Bank:Savings  $100.00

2026-03-25 * Costco
    ; lf_txn_id: txn_split
    Assets:Bank:Checking  $-40.00
    Expenses:Groceries  $25.00
    Expenses:Household  $15.00
"""

MATCHED_JOURNAL = """\
2026-03-15 * Whole Foods
    ; lf_txn_id: txn_matched
    ; :manual:
    ; lf_match_id: match_01JZ0000000000000000000000
    Assets:Bank:Checking  USD -50.00
    Expenses:Groceries  USD 50.00
"""

ARCHIVE = """\
; Ledger Flow archived manual entries.

2026-03-15 Whole Foods
    ; lf_txn_id: txn_archived
    ; lf_match_id: match_01JZ0000000000000000000000
    ; :manual:
    Assets:Bank:Checking  USD -50.00
    Expenses:Groceries  USD 50.00
"""

MATCH_ID = "match_01JZ0000000000000000000000"


def _config(workspace: Path) -> AppConfig:
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
        tracked_accounts={
            "checking": {"display_name": "Checking", "ledger_account": "Assets:Bank:Checking"},
            "savings": {"display_name": "Savings", "ledger_account": "Assets:Bank:Savings"},
        },
    )


@pytest.fixture
def books(tmp_path: Path) -> AppConfig:
    config = _config(tmp_path / "workspace")
    (config.journal_dir / "2026.journal").write_text(JOURNAL, encoding="utf-8")
    refresh_projection(config)
    return config


@pytest.fixture
def matched(tmp_path: Path) -> AppConfig:
    config = _config(tmp_path / "workspace")
    (config.journal_dir / "2026.journal").write_text(MATCHED_JOURNAL, encoding="utf-8")
    (config.journal_dir / "archived-manual.journal").write_text(ARCHIVE, encoding="utf-8")
    refresh_projection(config)
    return config


def _text(config: AppConfig) -> str:
    return (config.journal_dir / "2026.journal").read_text(encoding="utf-8")


def _row(config: AppConfig, txn_id: str) -> sqlite3.Row | None:
    conn = sqlite3.connect(database_path(config.root_dir))
    conn.row_factory = sqlite3.Row
    with conn:
        row = conn.execute(
            "SELECT id, raw_block_hash, status FROM transactions WHERE id = ?", (txn_id,)
        ).fetchone()
    conn.close()
    return row


def _block_hash(config: AppConfig, txn_id: str) -> str:
    row = _row(config, txn_id)
    assert row is not None
    return row["raw_block_hash"]


def _postings(config: AppConfig, txn_id: str) -> list[str]:
    conn = sqlite3.connect(database_path(config.root_dir))
    with conn:
        rows = conn.execute(
            "SELECT account FROM postings WHERE transaction_id = ? ORDER BY posting_order",
            (txn_id,),
        ).fetchall()
    conn.close()
    return [account for (account,) in rows]


def _last_event(config: AppConfig) -> dict:
    return read_operation_events(config.root_dir)[-1]


@pytest.fixture
def run(books: AppConfig):
    """Apply verbs to one transaction and hand back the finished session."""

    def _run(txn_id: str, apply, *, expect_hash: str | None = None, **kwargs):
        with edit(books, **kwargs) as session:
            apply(session.open(txn_id, expect_hash=expect_hash))
        return session

    return _run


# ---------------------------------------------------------------------------
# Opening: identity and staleness
# ---------------------------------------------------------------------------


class TestOpening:
    def test_unknown_id_is_not_found(self, books: AppConfig) -> None:
        with pytest.raises(TransactionNotFound):
            with edit(books) as session:
                session.open("txn_nope")

    def test_stale_hash_is_refused_and_journal_untouched(self, books: AppConfig) -> None:
        before = _text(books)
        with pytest.raises(StaleTransaction):
            with edit(books) as session:
                session.open("txn_wf", expect_hash="sha256:stale").set_notes("x")
        assert _text(books) == before

    def test_current_hash_is_accepted(self, books: AppConfig, run) -> None:
        run("txn_wf", lambda t: t.set_notes("ok"), expect_hash=_block_hash(books, "txn_wf"))
        assert "; notes: ok" in _text(books)

    def test_reopening_after_an_edit_reuses_the_handle(self, books) -> None:
        original_hash = _block_hash(books, "txn_target")
        with edit(books) as session:
            transaction = session.open("txn_target", expect_hash=original_hash)
            transaction.set_notes("updated")
            reopened = session.open("txn_target", expect_hash=original_hash)
            assert reopened is transaction
            assert reopened.notes == "updated"
            with pytest.raises(StaleTransaction):
                session.open("txn_target", expect_hash="sha256:stale")
        assert "; notes: updated" in _text(books)

    def test_deleted_handles_are_refused(self, books) -> None:
        with edit(books) as session:
            transaction = session.open("txn_target")
            transaction.delete()
            with pytest.raises(TransactionNotFound, match="deleted"):
                session.open("txn_target")
            with pytest.raises(TransactionNotFound, match="deleted"):
                transaction.set_notes("wrong block")
        assert _row(books, "txn_target") is None
        assert _row(books, "txn_wf") is not None

    def test_handles_are_closed_after_exit(self, books) -> None:
        with edit(books) as session:
            transaction = session.open("txn_target")
        with pytest.raises(EditError, match="closed"):
            transaction.set_notes("too late")
        with pytest.raises(EditError, match="closed"):
            session.open("txn_target")


# ---------------------------------------------------------------------------
# Reading postings by role
# ---------------------------------------------------------------------------


class TestRoles:
    def test_roles_resolve_on_an_ordinary_transaction(self, books: AppConfig) -> None:
        with edit(books) as session:
            txn = session.open("txn_wf")
            assert txn.source_account == "Assets:Bank:Checking"
            assert txn.category_account == "Expenses:Groceries"

    def test_transfer_has_no_category_account(self, books: AppConfig) -> None:
        with edit(books) as session:
            assert session.open("txn_transfer").category_account is None

    def test_split_refuses_to_name_one_category(self, books: AppConfig) -> None:
        with pytest.raises(SplitTransaction):
            with edit(books) as session:
                assert session.open("txn_split").category_account


# ---------------------------------------------------------------------------
# set_category
# ---------------------------------------------------------------------------


class TestSetCategory:
    def test_sets_the_category_and_records_the_prior_value(self, books: AppConfig, run) -> None:
        session = run("txn_target", lambda t: t.set_category("Expenses:Groceries"))

        assert _postings(books, "txn_target") == [
            "Assets:Bank:Checking",
            "Expenses:Groceries",
        ]
        event = _last_event(books)
        assert event["payload"]["previous_account"] == "Expenses:Unknown"
        assert event["payload"]["new_account"] == "Expenses:Groceries"
        assert event["payload"]["txn_id"] == "txn_target"
        assert session.result.operation_id == event["id"]

    def test_reset_to_uncategorized(self, books: AppConfig, run) -> None:
        run("txn_wf", lambda t: t.set_category(None))
        assert "Expenses:Unknown" in _text(books)

    def test_amount_and_alignment_survive(self, books: AppConfig, run) -> None:
        run("txn_target", lambda t: t.set_category("Expenses:Groceries"))
        assert "    Expenses:Groceries  $30.00" in _text(books)

    def test_already_uncategorized(self, books: AppConfig) -> None:
        with pytest.raises(AlreadyInState, match="already uncategorized"):
            with edit(books) as session:
                session.open("txn_target").set_category(None)

    def test_already_this_category(self, books: AppConfig) -> None:
        with pytest.raises(AlreadyInState, match="already has this category"):
            with edit(books) as session:
                session.open("txn_wf").set_category("Expenses:Groceries")

    def test_transfer_is_refused(self, books: AppConfig) -> None:
        with pytest.raises(NotACategory):
            with edit(books) as session:
                session.open("txn_transfer").set_category("Expenses:Groceries")

    def test_split_is_refused(self, books: AppConfig) -> None:
        with pytest.raises(SplitTransaction):
            with edit(books) as session:
                session.open("txn_split").set_category("Expenses:Groceries")


# ---------------------------------------------------------------------------
# set_source_account
# ---------------------------------------------------------------------------


class TestSetSourceAccount:
    def test_moves_the_tracked_leg(self, books: AppConfig, run) -> None:
        run("txn_wf", lambda t: t.set_source_account("Assets:Bank:Savings"))
        assert _postings(books, "txn_wf") == ["Assets:Bank:Savings", "Expenses:Groceries"]

    def test_untracked_target_is_refused(self, books: AppConfig) -> None:
        with pytest.raises(NotTracked):
            with edit(books) as session:
                session.open("txn_wf").set_source_account("Assets:Nope")

    def test_already_this_account(self, books: AppConfig) -> None:
        with pytest.raises(AlreadyInState):
            with edit(books) as session:
                session.open("txn_wf").set_source_account("Assets:Bank:Checking")

    def test_two_tracked_legs_are_refused(self, books: AppConfig) -> None:
        with pytest.raises(SplitTransaction):
            with edit(books) as session:
                session.open("txn_transfer").set_source_account("Assets:Bank:Savings")


# ---------------------------------------------------------------------------
# set_status / set_notes / metadata / tags
# ---------------------------------------------------------------------------


class TestSetStatus:
    def test_sets_status_and_records_prior(self, books: AppConfig, run) -> None:
        run("txn_target", lambda t: t.set_status(TransactionStatus.cleared))

        assert _row(books, "txn_target")["status"] == "cleared"
        payload = _last_event(books)["payload"]
        assert payload["previous_status"] == "unmarked"
        assert payload["new_status"] == "cleared"

    def test_already_this_status(self, books: AppConfig) -> None:
        with pytest.raises(AlreadyInState):
            with edit(books) as session:
                session.open("txn_wf").set_status(TransactionStatus.cleared)


class TestNotes:
    def test_insert_update_remove(self, books: AppConfig, run) -> None:
        run("txn_wf", lambda t: t.set_notes("first"))
        assert "    ; notes: first" in _text(books)

        run("txn_wf", lambda t: t.set_notes("second"))
        text = _text(books)
        assert "    ; notes: second" in text
        assert "first" not in text

        run("txn_wf", lambda t: t.set_notes(""))
        assert "; notes:" not in _text(books)

    def test_records_the_prior_note(self, books: AppConfig, run) -> None:
        run("txn_wf", lambda t: t.set_notes("first"))
        run("txn_wf", lambda t: t.set_notes("second"))

        payload = _last_event(books)["payload"]
        assert payload["previous_notes"] == "first"
        assert payload["notes"] == "second"

    def test_unchanged_note_is_refused(self, books: AppConfig, run) -> None:
        run("txn_wf", lambda t: t.set_notes("same"))
        with pytest.raises(AlreadyInState):
            with edit(books) as session:
                session.open("txn_wf").set_notes("same")


class TestMetadataAndTags:
    def test_metadata_round_trips(self, books: AppConfig, run) -> None:
        run("txn_wf", lambda t: t.set_metadata("lf_match_id", "m1"))
        assert "    ; lf_match_id: m1" in _text(books)

        run("txn_wf", lambda t: t.clear_metadata("lf_match_id"))
        assert "lf_match_id" not in _text(books)

    def test_metadata_change_is_logged_for_the_inverse(self, books: AppConfig, run) -> None:
        run("txn_wf", lambda t: t.set_metadata("lf_match_id", "m1"))
        log = _last_event(books)["payload"]["metadata"]["txn_wf"]["lf_match_id"]
        assert log == {"previous": None, "new": "m1"}

    def test_tags_round_trip(self, books: AppConfig, run) -> None:
        run("txn_wf", lambda t: t.set_tag("manual"))
        assert "    ; :manual:" in _text(books)

        run("txn_wf", lambda t: t.clear_tag("manual"))
        assert ":manual:" not in _text(books)

    def test_lf_txn_id_stays_first(self, books: AppConfig, run) -> None:
        run("txn_wf", lambda t: t.set_notes("keep order"))
        lines = _text(books).splitlines()
        header = lines.index("2026-03-15 * Whole Foods")
        assert lines[header + 1] == "    ; lf_txn_id: txn_wf"


class TestVerbResults:
    @pytest.mark.parametrize(
        ("apply", "expected"),
        [
            (lambda t: t.set_category(" Expenses:Groceries "),
             AccountChange("Expenses:Unknown", "Expenses:Groceries")),
            (lambda t: t.set_source_account(" Assets:Bank:Savings "),
             AccountChange("Assets:Bank:Checking", "Assets:Bank:Savings")),
            (lambda t: t.set_status(TransactionStatus.cleared), TransactionStatus.unmarked),
            (lambda t: t.set_notes("a note"), ""),
            (lambda t: t.set_metadata("lf_match_id", "m1"), None),
            (lambda t: t.set_tag("manual"), False),
        ],
    )
    def test_verb_returns_the_previous_and_applied_state(self, books, apply, expected) -> None:
        with edit(books) as session:
            assert apply(session.open("txn_target")) == expected


# ---------------------------------------------------------------------------
# delete / restore
# ---------------------------------------------------------------------------


class TestDeleteAndRestore:
    def test_delete_removes_the_block_and_its_separator(self, books: AppConfig, run) -> None:
        run("txn_wf", lambda t: t.delete())

        text = _text(books)
        assert "Whole Foods" not in text
        assert "\n\n\n" not in text
        assert _row(books, "txn_wf") is None

    def test_delete_records_the_block_for_its_inverse(self, books: AppConfig, run) -> None:
        run("txn_target", lambda t: t.delete())

        payload = _last_event(books)["payload"]
        assert payload["deleted_block"].startswith("2026-03-20 Target")
        assert payload["deleted_journal_path"] == "journals/2026.journal"

    def test_restore_puts_the_block_back_in_date_order(self, books: AppConfig) -> None:
        before = _text(books)
        with edit(books) as session:
            session.open("txn_target").delete()
        block = _last_event(books)["payload"]["deleted_block"]

        with edit(books) as session:
            session.restore("journals/2026.journal", block)

        assert _text(books) == before

    def test_restore_refuses_to_duplicate(self, books: AppConfig) -> None:
        block = "2026-03-20 Target\n    ; lf_txn_id: txn_target\n    Assets:Bank:Checking  $-1.00\n    Expenses:Unknown  $1.00"
        with pytest.raises(AlreadyInState):
            with edit(books) as session:
                session.restore("journals/2026.journal", block)


# ---------------------------------------------------------------------------
# Byte preservation, composition, symmetry
# ---------------------------------------------------------------------------


class TestBytePreservation:
    def test_only_the_edited_line_changes(self, books: AppConfig, run) -> None:
        before = _text(books).splitlines()
        run("txn_target", lambda t: t.set_category("Expenses:Groceries"))
        after = _text(books).splitlines()

        assert len(before) == len(after)
        differing = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        assert len(differing) == 1
        assert "Expenses:Unknown" in before[differing[0]]

    def test_an_externally_inserted_block_above_survives(self, books: AppConfig, run) -> None:
        journal = books.journal_dir / "2026.journal"
        journal.write_text(
            "2026-03-01 * Inserted Externally\n"
            "    Assets:Bank:Checking  $-1.00\n"
            "    Expenses:Groceries  $1.00\n\n" + JOURNAL,
            encoding="utf-8",
        )
        refresh_projection(books)

        run("txn_target", lambda t: t.set_category("Expenses:Groceries"))

        text = _text(books)
        assert text.startswith(
            "2026-03-01 * Inserted Externally\n"
            "    Assets:Bank:Checking  $-1.00\n"
            "    Expenses:Groceries  $1.00\n"
        )

    def test_trailing_newline_is_preserved_when_absent(self, tmp_path: Path) -> None:
        config = _config(tmp_path / "workspace")
        (config.journal_dir / "2026.journal").write_text(
            JOURNAL.rstrip("\n"), encoding="utf-8"
        )
        refresh_projection(config)

        with edit(config) as session:
            session.open("txn_wf").set_notes("no newline")

        assert not (config.journal_dir / "2026.journal").read_text(
            encoding="utf-8"
        ).endswith("\n\n")


class TestSessionActions:
    @pytest.mark.parametrize("second_id", ["txn_target", "txn_wf"])
    def test_a_second_action_refuses_the_entire_session(self, books: AppConfig, second_id) -> None:
        before = _text(books)
        events_before = len(read_operation_events(books.root_dir))
        with pytest.raises(ActionConflict, match="only one action"):
            with edit(books) as session:
                session.open("txn_target").set_category("Expenses:Groceries")
                session.open(second_id).set_category("Expenses:Household")
        assert _text(books) == before
        assert len(read_operation_events(books.root_dir)) == events_before

    def test_catching_a_second_action_refusal_cannot_commit(self, books: AppConfig) -> None:
        before = _text(books)
        events_before = len(read_operation_events(books.root_dir))
        with pytest.raises(ActionConflict, match="cannot commit"):
            with edit(books) as session:
                session.open("txn_target").set_category("Expenses:Groceries")
                with pytest.raises(ActionConflict):
                    session.open("txn_wf").set_notes("both")
        assert _text(books) == before
        assert len(read_operation_events(books.root_dir)) == events_before

    def test_reading_another_transaction_does_not_choose_the_operation_target(self, books) -> None:
        with edit(books) as session:
            session.open("txn_wf")
            session.open("txn_target").set_category("Expenses:Groceries")
        event = _last_event(books)
        assert event["type"] == "transaction.recategorized.v1"
        assert event["payload"]["txn_id"] == "txn_target"
        assert undo_event(books, event["id"]).outcome == UndoOutcome.SUCCESS
        assert _text(books) == JOURNAL

    def test_reading_records_nothing(self, books) -> None:
        count = len(read_operation_events(books.root_dir))
        with edit(books) as session:
            assert session.open("txn_wf").notes == ""
        assert session.result is None
        assert len(read_operation_events(books.root_dir)) == count

    def test_result_carries_post_edit_identity(self, books: AppConfig) -> None:
        stale = _block_hash(books, "txn_target")

        with edit(books) as session:
            session.open("txn_target").set_category("Expenses:Groceries")

        identity = session.result.identity("txn_target")
        assert identity.txn_id == "txn_target"
        assert identity.block_hash == _block_hash(books, "txn_target")
        assert identity.block_hash != stale


class TestRecordedUndo:
    @pytest.mark.parametrize("txn_id, apply, event_type", [
        ("txn_target", lambda t: t.set_category("Expenses:Groceries"), "transaction.recategorized.v1"),
        ("txn_wf", lambda t: t.set_source_account("Assets:Bank:Savings"), "transaction.account_reassigned.v1"),
        ("txn_target", lambda t: t.set_status(TransactionStatus.cleared), "transaction.status_toggled.v1"),
        ("txn_wf", lambda t: t.set_notes("note"), "transaction.notes_updated.v1"),
        ("txn_target", lambda t: t.delete(), "transaction.deleted.v1"),
    ])
    def test_the_verb_records_an_event_that_undo_restores(self, books, run, txn_id, apply, event_type):
        before = _text(books)
        run(txn_id, apply)
        event = _last_event(books)
        assert event["type"] == event_type
        result = undo_event(books, event["id"])
        assert result.outcome == UndoOutcome.SUCCESS
        assert _text(books) == before
        compensation = _last_event(books)
        assert compensation["type"] == f"{event_type}.compensated.v1"
        assert compensation["compensates"] == event["id"]
        assert compensation["payload"]["compensated_event_id"] == event["id"]


class TestSymmetry:
    @pytest.mark.parametrize(
        ("txn_id", "forward", "inverse"),
        [
            (
                "txn_target",
                lambda t: t.set_category("Expenses:Groceries"),
                lambda t: t.set_category("Expenses:Unknown"),
            ),
            (
                "txn_wf",
                lambda t: t.set_source_account("Assets:Bank:Savings"),
                lambda t: t.set_source_account("Assets:Bank:Checking"),
            ),
            (
                "txn_target",
                lambda t: t.set_status(TransactionStatus.cleared),
                lambda t: t.set_status(TransactionStatus.unmarked),
            ),
            (
                "txn_wf",
                lambda t: t.set_notes("a note"),
                lambda t: t.set_notes(""),
            ),
            (
                "txn_wf",
                lambda t: t.set_metadata("lf_match_id", "m1"),
                lambda t: t.clear_metadata("lf_match_id"),
            ),
            (
                "txn_wf",
                lambda t: t.set_tag("manual"),
                lambda t: t.clear_tag("manual"),
            ),
        ],
    )
    def test_forward_then_inverse_restores_the_journal(
        self, books: AppConfig, run, txn_id, forward, inverse
    ) -> None:
        before = _text(books)

        run(txn_id, forward)
        assert _text(books) != before
        run(txn_id, inverse)

        assert _text(books) == before

    def test_delete_then_restore_restores_the_journal(self, books: AppConfig) -> None:
        before = _text(books)

        with edit(books) as session:
            block = session.open("txn_wf").delete()

        with edit(books) as session:
            session.restore("journals/2026.journal", block)

        assert _text(books) == before


# ---------------------------------------------------------------------------
# unmatch / match — the composition proof
# ---------------------------------------------------------------------------


class TestUnmatchAndMatch:
    @pytest.mark.parametrize("recorded", [{}, "invalid", {
        "txn_id": "txn_matched", "match_id": MATCH_ID,
        "manual_block": "", "archive_path": "journals/archived-manual.journal",
        "category": "Expenses:Groceries",
    }])
    def test_incomplete_restoration_is_a_domain_refusal(self, recorded):
        with pytest.raises(EditError, match="Incomplete event payload"):
            MatchRestoration.from_payload({"match_restoration": recorded})

    def test_unmatch_unstamps_restores_and_empties_the_archive(self, matched: AppConfig) -> None:
        with edit(matched) as session:
            session.unmatch("txn_matched", match_id=MATCH_ID)

        text = (matched.journal_dir / "2026.journal").read_text(encoding="utf-8")
        imported = text.split("2026-03-15 Whole Foods")[0]
        assert "lf_match_id" not in imported
        assert ":manual:" not in imported
        assert "Expenses:Unknown" in imported
        assert "2026-03-15 Whole Foods" in text
        assert not (matched.journal_dir / "archived-manual.journal").exists()

    def test_unmatch_is_one_operation_carrying_its_inverse(self, matched: AppConfig) -> None:
        with edit(matched) as session:
            session.unmatch("txn_matched", match_id=MATCH_ID)

        payload = _last_event(matched)["payload"]
        assert payload["match_id"] == MATCH_ID
        assert payload["txn_id"] == "txn_matched"
        assert payload["previous_account"] == "Expenses:Groceries"
        assert payload["deleted_journal_path"] == "journals/archived-manual.journal"
        assert "lf_match_id" not in payload["restored_block"]

    def test_unknown_match_is_not_found(self, matched: AppConfig) -> None:
        with pytest.raises(TransactionNotFound):
            with edit(matched) as session:
                session.unmatch("txn_matched", match_id="match_nope")

    def test_match_is_the_inverse_of_unmatch(self, matched: AppConfig) -> None:
        with edit(matched) as session:
            restoration = session.unmatch("txn_matched", match_id=MATCH_ID)
        payload = _last_event(matched)["payload"]
        assert MatchRestoration.from_payload(payload) == restoration

        with edit(matched) as session:
            session.match(restoration)

        text = (matched.journal_dir / "2026.journal").read_text(encoding="utf-8")
        assert text.count("2026-03-15") == 1
        assert f"; lf_match_id: {MATCH_ID}" in text
        assert "; :manual:" in text
        assert "Expenses:Groceries" in text
        assert "Expenses:Unknown" not in text

        archive = (matched.journal_dir / "archived-manual.journal").read_text(encoding="utf-8")
        assert "2026-03-15 Whole Foods" in archive
        assert f"; lf_match_id: {MATCH_ID}" in archive

    def test_recorded_unmatch_can_be_undone(self, matched):
        before = (matched.journal_dir / "2026.journal").read_text()
        with edit(matched) as session:
            session.unmatch("txn_matched", match_id=MATCH_ID)
        event = _last_event(matched)
        assert event["type"] == "transaction.unmatched.v1"
        assert undo_event(matched, event["id"]).outcome == UndoOutcome.SUCCESS
        assert (matched.journal_dir / "2026.journal").read_text() == before

    def test_uncategorized_unmatch_keeps_an_exact_category_for_its_inverse(self, matched):
        path = matched.journal_dir / "2026.journal"
        path.write_text(MATCHED_JOURNAL.replace("Expenses:Groceries", "Expenses:Unknown"))
        with edit(matched) as session:
            session.unmatch("txn_matched", match_id=MATCH_ID)
        event = _last_event(matched)
        assert event["payload"]["match_restoration"]["category"] == "Expenses:Unknown"
        assert undo_event(matched, event["id"]).outcome == UndoOutcome.SUCCESS
        assert "Expenses:Unknown" in path.read_text()
