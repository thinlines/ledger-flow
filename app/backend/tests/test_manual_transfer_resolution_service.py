from __future__ import annotations

from pathlib import Path

import pytest

from services.account_register_service import build_account_register
from services.config_service import AppConfig
from services.import_service import _build_existing_map, _classify_transaction, _parse_transaction
from services.manual_transfer_resolution_service import (
    apply_manual_transfer_resolution,
    preview_manual_transfer_resolution,
)
from services.transfer_service import (
    MANUAL_TRANSFER_RESOLUTION_METADATA_KEY,
    MANUAL_TRANSFER_RESOLUTION_METADATA_VALUE,
    transfer_pair_account,
)
from services.workspace_service import ensure_workspace_journal_includes


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
        institution_templates={
            "wells_fargo": {
                "name": "Wells Fargo",
            }
        },
        import_accounts={
            "checking_import": {
                "display_name": "Checking Import",
                "institution": "wells_fargo",
                "ledger_account": "Assets:Bank:Checking",
                "tracked_account_id": "checking",
            },
            "savings_import": {
                "display_name": "Savings Import",
                "institution": "wells_fargo",
                "ledger_account": "Assets:Bank:Savings",
                "tracked_account_id": "savings",
            },
        },
        tracked_accounts={
            "checking": {
                "display_name": "Checking",
                "ledger_account": "Assets:Bank:Checking",
                "import_account_id": "checking_import",
            },
            "savings": {
                "display_name": "Savings",
                "ledger_account": "Assets:Bank:Savings",
                "import_account_id": "savings_import",
            },
            "vehicle": {
                "display_name": "Vehicle",
                "ledger_account": "Assets:Vehicle:Subaru",
                "import_account_id": None,
            },
        },
        payee_aliases="payee_aliases.csv",
    )


def _write_year_journal(config: AppConfig, body: str) -> Path:
    journal_path = config.journal_dir / "2026.journal"
    journal_path.write_text(body, encoding="utf-8")
    ensure_workspace_journal_includes(config)
    return journal_path


def _pending_transfer_body(config: AppConfig) -> str:
    transfer_account = transfer_pair_account("checking", "savings")
    return (
        f"""
2026/03/12 Transfer to savings
    ; import_account_id: checking_import
    ; source_identity: tx-checking
    ; source_payload_hash: payload-checking
    ; transfer_id: transfer-1
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: savings
    {transfer_account}  USD 50.00
    Assets:Bank:Checking  USD -50.00
""".strip()
        + "\n"
    )


def _savings_counterpart_metadata_lines(
    *,
    account_cfg: dict,
    transfer_account: str,
    payee: str = "Transfer to savings",
    transfer_posting_account: str | None = None,
) -> list[str]:
    category_account = transfer_posting_account or transfer_account
    raw_lines = [
        f"2026/03/12 {payee}",
        f"    {category_account}  USD -50.00",
        "    Assets:Bank:Savings  USD 50.00",
    ]
    parsed = _parse_transaction(
        raw_lines,
        import_account_id="savings_import",
        institution_account=str(account_cfg["ledger_account"]),
        base_currency="USD",
    )
    return [
        raw_lines[0],
        "    ; import_account_id: savings_import",
        f"    ; source_identity: {parsed['sourceIdentity']}",
        f"    ; source_payload_hash: {parsed['sourcePayloadHash']}",
        "    ; importer_version: mvp2",
        *raw_lines[1:],
    ]


def test_preview_manual_transfer_resolution_returns_guided_preview(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(config, _pending_transfer_body(config))

    register = build_account_register(config, "checking")
    token = register["entries"][0]["manualResolutionToken"]

    preview = preview_manual_transfer_resolution(config, token)

    assert preview["sourceAccountName"] == "Checking"
    assert preview["destinationAccountName"] == "Savings"
    assert preview["fromAccountName"] == "Checking"
    assert preview["toAccountName"] == "Savings"
    assert preview["amount"] == 50.0
    assert preview["payee"] == "Transfer to savings"
    assert "no imported counterpart is expected" in preview["warning"].lower()


def test_apply_manual_transfer_resolution_matches_source_and_appends_counterpart(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    journal_path = _write_year_journal(config, _pending_transfer_body(config))

    register = build_account_register(config, "checking")
    token = register["entries"][0]["manualResolutionToken"]

    result = apply_manual_transfer_resolution(config, token)

    content = journal_path.read_text(encoding="utf-8")
    assert result["applied"] is True
    assert Path(result["backupPath"]).exists()
    assert content.count("; transfer_match_state: matched") == 2
    assert "; transfer_match_state: pending" not in content
    assert content.count(f"; {MANUAL_TRANSFER_RESOLUTION_METADATA_KEY}: {MANUAL_TRANSFER_RESOLUTION_METADATA_VALUE}") == 2
    assert content.count("; transfer_id: transfer-1") == 2
    assert "    ; import_account_id: checking_import" in content
    assert "    ; import_account_id: savings_import" in content
    assert "    ; source_identity: tx-checking" in content
    assert "    ; importer_version: mvp2" in content

    checking_register = build_account_register(config, "checking")
    savings_register = build_account_register(config, "savings")

    assert not [entry for entry in checking_register["entries"] if entry["transferState"] == "pending"]
    assert checking_register["entries"][0]["transferState"] == "matched"
    assert checking_register["entries"][0]["manualResolutionNote"] == (
        "The missing side was added manually because no imported counterpart was expected."
    )
    assert not [entry for entry in savings_register["entries"] if entry["transferState"] == "pending"]
    assert savings_register["entries"][0]["summary"] == "Transfer · Checking"
    assert savings_register["entries"][0]["amount"] == 50.0
    assert savings_register["entries"][0]["manualResolutionNote"] == (
        "The missing side was added manually because no imported counterpart was expected."
    )

    existing_map = _build_existing_map(config, "savings_import", journal_path)
    duplicate_candidate = _parse_transaction(
        [
            "2026/03/12 Transfer to savings",
            f"    {transfer_pair_account('checking', 'savings')}  USD -50.00",
            "    Assets:Bank:Savings  USD 50.00",
        ],
        import_account_id="savings_import",
        institution_account="Assets:Bank:Savings",
        base_currency="USD",
    )
    conflict_candidate = _parse_transaction(
        [
            "2026/03/12 Transfer to savings",
            "    Expenses:Other  USD -50.00",
            "    Assets:Bank:Savings  USD 50.00",
        ],
        import_account_id="savings_import",
        institution_account="Assets:Bank:Savings",
        base_currency="USD",
    )

    assert _classify_transaction(duplicate_candidate, existing_map) == "duplicate"
    assert _classify_transaction(conflict_candidate, existing_map) == "conflict"


def test_apply_manual_transfer_resolution_accepts_token_from_peer_pending_row(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    journal_path = _write_year_journal(config, _pending_transfer_body(config))

    peer_register = build_account_register(config, "savings")
    token = peer_register["entries"][0]["manualResolutionToken"]

    apply_manual_transfer_resolution(config, token)

    content = journal_path.read_text(encoding="utf-8")
    assert content.count("; transfer_match_state: matched") == 2
    assert "; transfer_match_state: pending" not in content
    assert build_account_register(config, "savings")["entries"][0]["transferState"] == "matched"


def test_preview_manual_transfer_resolution_rejects_duplicate_destination_identity(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    transfer_account = transfer_pair_account("checking", "savings")
    existing_lines = _savings_counterpart_metadata_lines(
        account_cfg=config.import_accounts["savings_import"],
        transfer_account=transfer_account,
    )
    body = _pending_transfer_body(config) + "\n" + "\n".join(existing_lines) + "\n"
    _write_year_journal(config, body)

    token = build_account_register(config, "checking")["entries"][0]["manualResolutionToken"]

    with pytest.raises(ValueError, match="already exists"):
        preview_manual_transfer_resolution(config, token)


def test_preview_manual_transfer_resolution_rejects_conflicting_destination_identity(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    transfer_account = transfer_pair_account("checking", "savings")
    existing_lines = _savings_counterpart_metadata_lines(
        account_cfg=config.import_accounts["savings_import"],
        transfer_account=transfer_account,
        transfer_posting_account="Expenses:Other",
    )
    body = _pending_transfer_body(config) + "\n" + "\n".join(existing_lines) + "\n"
    _write_year_journal(config, body)

    token = build_account_register(config, "checking")["entries"][0]["manualResolutionToken"]

    with pytest.raises(ValueError, match="different details"):
        preview_manual_transfer_resolution(config, token)


def test_apply_manual_transfer_resolution_rejects_stale_pending_state_without_appending_counterpart(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    journal_path = _write_year_journal(config, _pending_transfer_body(config))

    token = build_account_register(config, "checking")["entries"][0]["manualResolutionToken"]
    preview_manual_transfer_resolution(config, token)

    journal_path.write_text(
        journal_path.read_text(encoding="utf-8").replace(
            "; transfer_match_state: pending",
            "; transfer_match_state: matched",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="no longer eligible"):
        apply_manual_transfer_resolution(config, token)

    content = journal_path.read_text(encoding="utf-8")
    assert content.count("2026/03/12 Transfer to savings") == 1
