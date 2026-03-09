from pathlib import Path

from services.config_service import load_config
from services.import_service import scan_candidates
from services.workspace_service import WorkspaceManager


def test_bootstrap_workspace_writes_import_accounts_and_templates(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "app")
    workspace_root = tmp_path / "workspace"

    manager.bootstrap_workspace(
        workspace_path=workspace_root,
        workspace_name="Test Books",
        base_currency="USD",
        start_year=2026,
        import_accounts=[
            {
                "institutionId": "wells_fargo",
                "displayName": "Wells Fargo Checking",
                "ledgerAccount": "Assets:Bank:Wells Fargo:Checking",
                "last4": "1234",
            },
            {
                "institutionId": "wells_fargo",
                "displayName": "Wells Fargo Savings",
                "ledgerAccount": "Assets:Bank:Wells Fargo:Savings",
                "last4": "5678",
            },
        ],
    )

    config = load_config(workspace_root / "settings" / "workspace.toml")

    assert list(config.institution_templates) == ["wells_fargo"]
    assert sorted(config.import_accounts) == [
        "wells_fargo_checking_1234",
        "wells_fargo_savings_5678",
    ]
    assert config.import_accounts["wells_fargo_checking_1234"]["ledger_account"] == "Assets:Bank:Wells Fargo:Checking"
    assert config.import_accounts["wells_fargo_savings_5678"]["institution"] == "wells_fargo"

    accounts_dat = workspace_root / "rules" / "10-accounts.dat"
    content = accounts_dat.read_text(encoding="utf-8")
    assert "account Assets:Bank:Wells Fargo:Checking" in content
    assert "account Assets:Bank:Wells Fargo:Savings" in content
    assert "account Expenses:Unknown" in content


def test_scan_candidates_detects_import_account_from_inbox_name(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "app")
    workspace_root = tmp_path / "workspace"

    manager.bootstrap_workspace(
        workspace_path=workspace_root,
        workspace_name="Test Books",
        base_currency="USD",
        start_year=2026,
        import_accounts=[
            {
                "institutionId": "wells_fargo",
                "displayName": "Wells Fargo Checking",
                "ledgerAccount": "Assets:Bank:Wells Fargo:Checking",
                "last4": "1234",
            }
        ],
    )

    config = load_config(workspace_root / "settings" / "workspace.toml")
    candidate_id = next(iter(config.import_accounts))
    inbox_file = config.csv_dir / f"2026__{candidate_id}__march.csv"
    inbox_file.write_text("date,amount\n2026-03-01,-7.50\n", encoding="utf-8")

    candidates = scan_candidates(config)

    assert len(candidates) == 1
    assert candidates[0].detected_year == "2026"
    assert candidates[0].detected_import_account_id == candidate_id
    assert candidates[0].detected_institution_id == "wells_fargo"
    assert candidates[0].is_configured_import_account is True
