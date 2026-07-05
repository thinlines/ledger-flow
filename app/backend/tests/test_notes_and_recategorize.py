"""Notes read-path tests.

The write paths (notes update, recategorize with newCategory) are covered at
the endpoint seam in ``test_transaction_actions_by_id.py`` on the
``(lf_txn_id, raw_block_hash)`` contract; the inline reimplementations of
the old positional endpoint logic that used to live here died with it.
"""

from __future__ import annotations


class TestReadNotesFromRegister:
    """Notes parsed via metadata are included in register entries."""

    def test_notes_present_in_metadata(self) -> None:
        """Verify that META_RE (used by journal_query_service) captures '; notes: ...' lines."""
        from services.journal_query_service import META_RE

        line = "    ; notes: Weekly groceries"
        m = META_RE.match(line)
        assert m is not None
        assert m.group(1).strip().lower() == "notes"
        assert m.group(2).strip() == "Weekly groceries"

    def test_notes_absent_returns_none(self) -> None:
        """A comment without 'notes:' key is not captured as notes."""
        from services.journal_query_service import META_RE

        line = "    ; lf_source_identity: abc123"
        m = META_RE.match(line)
        assert m is not None
        # Key is 'lf_source_identity', not 'notes'.
        assert m.group(1).strip().lower() != "notes"

    def test_register_event_has_notes_field(self) -> None:
        """RegisterEvent dataclass includes a notes field."""
        from services.account_register_service import RegisterEvent
        from datetime import date
        from decimal import Decimal

        event = RegisterEvent(
            posted_on=date(2026, 3, 15),
            order=0,
            amount=Decimal("-50.00"),
            commodity="$",
            payee="Whole Foods",
            summary="Groceries",
            is_unknown=False,
            is_opening_balance=False,
            detail_lines=[],
            notes="Weekly groceries",
        )
        assert event.notes == "Weekly groceries"

    def test_register_event_notes_default_none(self) -> None:
        """RegisterEvent notes defaults to None."""
        from services.account_register_service import RegisterEvent
        from datetime import date
        from decimal import Decimal

        event = RegisterEvent(
            posted_on=date(2026, 3, 15),
            order=0,
            amount=Decimal("-50.00"),
            commodity="$",
            payee="Whole Foods",
            summary="Groceries",
            is_unknown=False,
            is_opening_balance=False,
            detail_lines=[],
        )
        assert event.notes is None
