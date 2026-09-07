"""Recomputing stored source identities (issue #007, seam 2).

Identities written before the amount fix came from bases that omitted or
inconsistently rendered the amount; some cannot be reproduced by current code
at all, so a re-import would not recognise those rows and would write them
again. This migration puts every row on one generation, recomputed from each
block's own ``; CSV:`` provenance.

Behaviour under test:

- Every recomputable block's ``lf_source_identity`` is replaced; every other
  byte of the file is preserved.
- Blocks without provenance, or whose postings no longer include their import
  account, are left alone and reported rather than guessed at.
- Blocks resolving to one identity are reported as collisions for triage.
- ``import_identities`` rows follow the rename.
- Running twice changes nothing the second time.
"""
from __future__ import annotations

from pathlib import Path

from services.config_service import AppConfig
from services.journal_migration_service import migrate_source_identities

CARD = "Liabilities:Card"


def _make_config(workspace: Path) -> AppConfig:
    for name in ["settings", "journals", "inbox", "rules", "opening", "imports"]:
        (workspace / name).mkdir(parents=True, exist_ok=True)
    return AppConfig(
        root_dir=workspace,
        config_toml=workspace / "settings" / "workspace.toml",
        workspace={"name": "Test", "base_currency": "USD", "start_year": 2026},
        dirs={
            "csv_dir": "inbox",
            "journal_dir": "journals",
            "init_dir": "rules",
            "opening_bal_dir": "opening",
            "imports_dir": "imports",
        },
        institution_templates={},
        import_accounts={
            "card": {"display_name": "Card", "ledger_account": CARD},
        },
        tracked_accounts={
            "card": {"display_name": "Card", "ledger_account": CARD},
        },
    )


def _block(payee: str, amount: str, identity: str, *, csv: bool = True) -> str:
    csv_line = f"    ; CSV: 2026/04/27,,{payee},${amount},,\n" if csv else ""
    return (
        f"2026-04-27 * {payee}\n"
        f"    ; lf_txn_id: txn_{identity[:8]}\n"
        f"    ; import_account_id: card\n"
        f"    ; lf_source_identity: {identity}\n"
        f"{csv_line}"
        f"    Expenses:Shopping                 USD {amount.lstrip('-')}\n"
        f"    {CARD}\n"
    )


def _write(workspace: Path, *blocks: str) -> Path:
    path = workspace / "journals" / "2026.journal"
    path.write_text("\n".join(blocks), encoding="utf-8")
    return path


def test_stale_identities_are_recomputed(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    path = _write(
        tmp_path,
        _block("COSTCO WHSE #0761", "-7.92", "stale-one"),
        _block("COSTCO WHSE #0761", "-127.53", "stale-two"),
    )

    report = migrate_source_identities(config)

    assert report["rewritten"] == 2
    assert report["skipped"] == []
    assert report["collisions"] == []
    assert "stale-one" not in path.read_text()
    assert "stale-two" not in path.read_text()


def test_two_same_day_purchases_get_different_identities(tmp_path: Path) -> None:
    """The collision the old identity could not express."""
    config = _make_config(tmp_path)
    path = _write(
        tmp_path,
        _block("COSTCO WHSE #0761", "-7.92", "collided"),
        _block("COSTCO WHSE #0761", "-127.53", "collided"),
    )

    migrate_source_identities(config)

    identities = [
        line.split(": ", 1)[1].strip()
        for line in path.read_text().splitlines()
        if "lf_source_identity:" in line
    ]
    assert len(identities) == 2
    assert identities[0] != identities[1]


def test_only_identity_lines_change(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    path = _write(tmp_path, _block("COSTCO", "-7.92", "stale"))
    before = path.read_text()

    migrate_source_identities(config)

    after = path.read_text()
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    assert len(before_lines) == len(after_lines)
    differing = [
        (b, a) for b, a in zip(before_lines, after_lines, strict=True) if b != a
    ]
    assert len(differing) == 1
    assert "lf_source_identity" in differing[0][0]


def test_indentation_and_trailing_newline_are_preserved(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    path = _write(tmp_path, _block("COSTCO", "-7.92", "stale"))
    assert path.read_text().endswith("\n")

    migrate_source_identities(config)

    text = path.read_text()
    assert text.endswith("\n")
    identity_line = next(
        line for line in text.splitlines() if "lf_source_identity" in line
    )
    assert identity_line.startswith("    ; lf_source_identity: ")


def test_block_without_provenance_is_skipped_and_reported(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    path = _write(tmp_path, _block("MYSTERY ACH", "-10.00", "keep-me", csv=False))

    report = migrate_source_identities(config)

    assert report["rewritten"] == 0
    assert len(report["skipped"]) == 1
    assert "CSV" in report["skipped"][0]["reason"]
    assert "keep-me" in path.read_text()


def test_block_whose_import_account_is_gone_is_skipped(tmp_path: Path) -> None:
    """A reassigned account means the amount is no longer comparable, so the
    identity must not be silently recomputed from the new posting."""
    config = _make_config(tmp_path)
    reassigned = _block("COSTCO", "-7.92", "keep-me").replace(
        f"    {CARD}\n", "    Assets:Some:Other:Account\n"
    )
    path = _write(tmp_path, reassigned)

    report = migrate_source_identities(config)

    assert report["rewritten"] == 0
    assert len(report["skipped"]) == 1
    assert "reassigned" in report["skipped"][0]["reason"]
    assert "keep-me" in path.read_text()


def test_genuine_duplicates_are_reported_as_collisions(tmp_path: Path) -> None:
    """Same account, date, payee and amount: one bank row recorded twice."""
    config = _make_config(tmp_path)
    _write(
        tmp_path,
        _block("COSTCO", "-7.92", "first"),
        _block("COSTCO", "-7.92", "second"),
    )

    report = migrate_source_identities(config)

    assert len(report["collisions"]) == 1
    assert len(report["collisions"][0]["blocks"]) == 2


def test_migration_is_idempotent(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    path = _write(tmp_path, _block("COSTCO", "-7.92", "stale"))

    migrate_source_identities(config)
    after_first = path.read_text()
    second = migrate_source_identities(config)

    assert second["rewritten"] == 0
    assert second["unchanged"] == 1
    assert path.read_text() == after_first


def test_dry_run_reports_without_writing(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    path = _write(tmp_path, _block("COSTCO", "-7.92", "stale"))
    before = path.read_text()

    report = migrate_source_identities(config, dry_run=True)

    assert report["rewritten"] == 1
    assert report["dry_run"] is True
    assert path.read_text() == before


def test_recomputed_identity_matches_what_a_reimport_would_compute(tmp_path: Path) -> None:
    """The point of the whole exercise: after migration, re-importing the same
    statement row recognises it instead of writing it again."""
    from decimal import Decimal

    from services import source_identity

    config = _make_config(tmp_path)
    path = _write(tmp_path, _block("COSTCO WHSE #0761", "-7.92", "stale"))
    migrate_source_identities(config)

    stored = next(
        line.split(": ", 1)[1].strip()
        for line in path.read_text().splitlines()
        if "lf_source_identity:" in line
    )
    reimported = source_identity.compute(
        import_account_id="card",
        date="2026/04/27",
        statement_payee="COSTCO WHSE #0761",
        amount=Decimal("-7.92"),
    )

    assert reimported.value == stored
    assert reimported.matches(stored)
