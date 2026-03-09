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


def test_bootstrap_workspace_without_accounts_reports_setup_progress(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "app")
    workspace_root = tmp_path / "workspace"

    manager.bootstrap_workspace(
        workspace_path=workspace_root,
        workspace_name="Test Books",
        base_currency="USD",
        start_year=2026,
        import_accounts=[],
    )

    config = load_config(workspace_root / "settings" / "workspace.toml")
    setup = manager.get_setup_state(config)

    assert setup["needsWorkspace"] is False
    assert setup["needsAccounts"] is True
    assert setup["needsFirstImport"] is False
    assert setup["needsReview"] is False
    assert setup["currentStep"] == "accounts"
    assert setup["completedSteps"] == ["workspace"]

    accounts_dat = workspace_root / "rules" / "10-accounts.dat"
    assert "account Expenses:Unknown" in accounts_dat.read_text(encoding="utf-8")


def test_upsert_import_account_adds_post_bootstrap_account_and_updates_setup_state(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "app")
    workspace_root = tmp_path / "workspace"

    manager.bootstrap_workspace(
        workspace_path=workspace_root,
        workspace_name="Test Books",
        base_currency="USD",
        start_year=2026,
        import_accounts=[],
    )

    config = load_config(workspace_root / "settings" / "workspace.toml")
    account_id, _ = manager.upsert_import_account(
        config,
        {
            "institutionId": "wells_fargo",
            "displayName": "Wells Fargo Checking",
            "last4": "1234",
        },
    )

    reloaded = load_config(workspace_root / "settings" / "workspace.toml")
    assert account_id == "wells_fargo_checking_1234"
    assert sorted(reloaded.import_accounts) == ["wells_fargo_checking_1234"]
    assert reloaded.import_accounts[account_id]["ledger_account"] == "Assets:Bank:Wells Fargo:Checking"
    assert list(reloaded.institution_templates) == ["wells_fargo"]

    setup = manager.get_setup_state(reloaded)
    assert setup["needsAccounts"] is False
    assert setup["needsFirstImport"] is True
    assert setup["currentStep"] == "import"
    assert setup["completedSteps"] == ["workspace", "accounts"]

    accounts_dat = workspace_root / "rules" / "10-accounts.dat"
    content = accounts_dat.read_text(encoding="utf-8")
    assert "account Assets:Bank:Wells Fargo:Checking" in content


def test_upsert_import_account_updates_existing_account_without_replacing_id(tmp_path: Path) -> None:
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
    account_id = next(iter(config.import_accounts))

    updated_id, updated_cfg = manager.upsert_import_account(
        config,
        {
            "institutionId": "wells_fargo",
            "displayName": "Primary Checking",
            "ledgerAccount": "Assets:Bank:Wells Fargo:Primary:Checking",
            "last4": "1234",
        },
        account_id=account_id,
    )

    assert updated_id == account_id
    assert updated_cfg["display_name"] == "Primary Checking"

    reloaded = load_config(workspace_root / "settings" / "workspace.toml")
    assert sorted(reloaded.import_accounts) == [account_id]
    assert reloaded.import_accounts[account_id]["display_name"] == "Primary Checking"
    assert reloaded.import_accounts[account_id]["ledger_account"] == "Assets:Bank:Wells Fargo:Primary:Checking"

    accounts_dat = workspace_root / "rules" / "10-accounts.dat"
    content = accounts_dat.read_text(encoding="utf-8")
    assert "account Assets:Bank:Wells Fargo:Primary:Checking" in content


def test_setup_state_detects_imported_activity_and_review_queue(tmp_path: Path) -> None:
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
    journal_path = config.journal_dir / "2026.journal"
    journal_path.write_text(
        "2026/03/01 Coffee Shop\n"
        "    Assets:Bank:Wells Fargo:Checking  $-7.50\n"
        "    Expenses:Unknown\n",
        encoding="utf-8",
    )

    setup = manager.get_setup_state(config)
    assert setup["needsFirstImport"] is False
    assert setup["needsReview"] is True
    assert setup["currentStep"] == "review"

    journal_path.write_text(
        "2026/03/01 Coffee Shop\n"
        "    Assets:Bank:Wells Fargo:Checking  $-7.50\n"
        "    Expenses:Food\n",
        encoding="utf-8",
    )

    refreshed = load_config(workspace_root / "settings" / "workspace.toml")
    done_state = manager.get_setup_state(refreshed)
    assert done_state["needsReview"] is False
    assert done_state["currentStep"] == "done"
    assert done_state["completedSteps"] == ["workspace", "accounts", "import", "review"]


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
