from pathlib import Path

from services.account_register_service import build_account_register
from services.config_service import load_config
from services.import_index import ImportIndex
from services.import_service import _classify_transaction, _parse_transaction
from services.import_service import scan_candidates
from services.workspace_service import (
    WorkspaceManager,
    ensure_journal_includes,
    ensure_standard_commodities_file,
)


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
    assert sorted(config.tracked_accounts) == [
        "wells_fargo_checking_1234",
        "wells_fargo_savings_5678",
    ]
    assert config.import_accounts["wells_fargo_checking_1234"]["ledger_account"] == "Assets:Bank:Wells Fargo:Checking"
    assert config.import_accounts["wells_fargo_savings_5678"]["institution"] == "wells_fargo"
    assert config.tracked_accounts["wells_fargo_checking_1234"]["import_account_id"] == "wells_fargo_checking_1234"

    accounts_dat = workspace_root / "rules" / "10-accounts.dat"
    content = accounts_dat.read_text(encoding="utf-8")
    assert "account Assets:Bank:Wells Fargo:Checking" in content
    assert "account Assets:Bank:Wells Fargo:Savings" in content
    assert "account Expenses:Unknown" in content
    assert "account Equity:Opening-Balances" in content

    year_journal = workspace_root / "journals" / "2026.journal"
    journal_content = year_journal.read_text(encoding="utf-8")
    assert journal_content.startswith(
        "include ../rules/10-accounts.dat\n"
        "include ../rules/12-tags.dat\n"
        "include ../rules/13-commodities.dat\n"
    )
    assert "; Test Books financial journal" in journal_content

    commodities_dat = workspace_root / "rules" / "13-commodities.dat"
    commodities_content = commodities_dat.read_text(encoding="utf-8")
    assert "commodity USD" in commodities_content
    assert "\tformat USD1,000.00" in commodities_content
    assert "commodity $" in commodities_content
    assert "\tformat $1,000.00" in commodities_content

    assert (workspace_root / "imports" / "import-log.ndjson").exists()


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
    assert sorted(reloaded.tracked_accounts) == ["wells_fargo_checking_1234"]
    assert reloaded.import_accounts[account_id]["ledger_account"] == "Assets:Bank:Wells Fargo:Checking"
    assert reloaded.tracked_accounts[account_id]["ledger_account"] == "Assets:Bank:Wells Fargo:Checking"
    assert reloaded.tracked_accounts[account_id]["import_account_id"] == account_id
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
    assert sorted(reloaded.tracked_accounts) == [account_id]
    assert reloaded.import_accounts[account_id]["display_name"] == "Primary Checking"
    assert reloaded.import_accounts[account_id]["ledger_account"] == "Assets:Bank:Wells Fargo:Primary:Checking"
    assert reloaded.tracked_accounts[account_id]["display_name"] == "Primary Checking"
    assert reloaded.tracked_accounts[account_id]["ledger_account"] == "Assets:Bank:Wells Fargo:Primary:Checking"

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


def test_upsert_tracked_account_creates_manual_account_with_opening_balance(tmp_path: Path) -> None:
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
    account_id, account_cfg = manager.upsert_tracked_account(
        config,
        {
            "displayName": "Cash Wallet",
            "ledgerAccount": "Assets:Cash:Wallet",
        },
        opening_balance="250.00",
        opening_balance_date="2026-01-15",
    )

    assert account_id == "cash_wallet"
    assert account_cfg["display_name"] == "Cash Wallet"

    reloaded = load_config(workspace_root / "settings" / "workspace.toml")
    assert sorted(reloaded.import_accounts) == []
    assert sorted(reloaded.tracked_accounts) == ["cash_wallet"]
    assert reloaded.tracked_accounts["cash_wallet"]["ledger_account"] == "Assets:Cash:Wallet"
    assert reloaded.tracked_accounts["cash_wallet"]["import_account_id"] is None

    accounts_dat = workspace_root / "rules" / "10-accounts.dat"
    content = accounts_dat.read_text(encoding="utf-8")
    assert "account Assets:Cash:Wallet" in content

    opening_file = workspace_root / "opening" / "cash_wallet.journal"
    opening_content = opening_file.read_text(encoding="utf-8")
    assert "2026-01-15 Opening balance" in opening_content
    assert "Assets:Cash:Wallet  USD 250.00" in opening_content


def test_upsert_tracked_account_accepts_null_institution_id(tmp_path: Path) -> None:
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
    account_id, account_cfg = manager.upsert_tracked_account(
        config,
        {
            "displayName": "Brokerage Cash",
            "ledgerAccount": "Assets:Investments:Brokerage:Cash",
            "institutionId": None,
            "last4": None,
        },
    )

    assert account_id == "brokerage_cash"
    assert account_cfg["institution"] is None
    assert account_cfg["last4"] is None

    reloaded = load_config(workspace_root / "settings" / "workspace.toml")
    assert reloaded.tracked_accounts["brokerage_cash"].get("institution") is None
    assert reloaded.tracked_accounts["brokerage_cash"].get("last4") is None
    assert reloaded.tracked_accounts["brokerage_cash"]["import_account_id"] is None


def test_upsert_import_account_keeps_opening_balance_in_sync_with_ledger_account(tmp_path: Path) -> None:
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
                "ledgerAccount": "Assets:Bank:Checking",
                "last4": "1234",
                "openingBalance": "1200.00",
                "openingBalanceDate": "2026-01-01",
            }
        ],
    )

    config = load_config(workspace_root / "settings" / "workspace.toml")
    account_id = next(iter(config.import_accounts))
    opening_file = workspace_root / "opening" / f"{account_id}.journal"
    assert "Assets:Bank:Checking  USD 1200.00" in opening_file.read_text(encoding="utf-8")

    updated_config = load_config(workspace_root / "settings" / "workspace.toml")
    manager.upsert_import_account(
        updated_config,
        {
            "institutionId": "wells_fargo",
            "displayName": "Primary Checking",
            "ledgerAccount": "Assets:Bank:Primary:Checking",
            "last4": "1234",
        },
        account_id=account_id,
    )

    updated_opening = opening_file.read_text(encoding="utf-8")
    assert "Assets:Bank:Primary:Checking  USD 1200.00" in updated_opening
    assert "2026-01-01 Opening balance" in updated_opening


def test_upsert_import_account_rewrites_existing_journal_postings_to_new_ledger_account(tmp_path: Path) -> None:
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
                "ledgerAccount": "Assets:Bank:Checking",
                "last4": "1234",
            }
        ],
    )

    config = load_config(workspace_root / "settings" / "workspace.toml")
    account_id = next(iter(config.import_accounts))
    journal_path = workspace_root / "journals" / "2026.journal"
    original_txn = _parse_transaction(
        [
            "2026/03/01 Coffee Shop",
            "    Assets:Bank:Checking  $-7.50",
            "    Expenses:Food",
        ],
        import_account_id=account_id,
        institution_account="Assets:Bank:Checking",
    )
    journal_path.write_text(
        "2026/03/01 Coffee Shop\n"
        f"    ; import_account_id: {account_id}\n"
        f"    ; source_identity: {original_txn['sourceIdentity']}\n"
        f"    ; source_payload_hash: {original_txn['sourcePayloadHash']}\n"
        "    ; source_file_sha256: source-file-1\n"
        "    Assets:Bank:Checking  $-7.50\n"
        "    Expenses:Food\n",
        encoding="utf-8",
    )
    ImportIndex(workspace_root / ".workflow" / "state.db").upsert_transactions(
        import_account_id=account_id,
        year="2026",
        journal_path=journal_path,
        source_file_sha256="source-file-1",
        txns=[
            {
                "sourceIdentity": original_txn["sourceIdentity"],
                "sourcePayloadHash": original_txn["sourcePayloadHash"],
            }
        ],
    )

    manager.upsert_import_account(
        config,
        {
            "institutionId": "wells_fargo",
            "displayName": "Primary Checking",
            "ledgerAccount": "Assets:Bank:Primary:Checking",
            "last4": "1234",
        },
        account_id=account_id,
    )

    updated_journal = journal_path.read_text(encoding="utf-8")
    assert "Assets:Bank:Primary:Checking  $-7.50" in updated_journal
    assert "Assets:Bank:Checking  $-7.50" not in updated_journal

    reloaded = load_config(workspace_root / "settings" / "workspace.toml")
    reparsed_txn = _parse_transaction(
        [
            "2026/03/01 Coffee Shop",
            "    Assets:Bank:Primary:Checking  $-7.50",
            "    Expenses:Food",
        ],
        import_account_id=account_id,
        institution_account="Assets:Bank:Primary:Checking",
    )
    assert (
        _classify_transaction(
            reparsed_txn,
            ImportIndex(workspace_root / ".workflow" / "state.db").get_identity_map(account_id),
        )
        == "duplicate"
    )
    assert f"; source_payload_hash: {reparsed_txn['sourcePayloadHash']}" in updated_journal

    register = build_account_register(reloaded, account_id)
    assert register["transactionCount"] == 1
    assert register["currentBalance"] == -7.5


def test_upsert_custom_import_account_creates_profile_and_links_tracked_account(tmp_path: Path) -> None:
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
    account_id, account_cfg = manager.upsert_custom_import_account(
        config,
        {
            "displayName": "Capital One Card",
            "ledgerAccount": "Liabilities:Cards:Capital One",
            "last4": "4242",
            "customProfile": {
                "displayName": "Capital One CSV",
                "encoding": "utf-8",
                "delimiter": ",",
                "skipRows": 0,
                "skipFooterRows": 0,
                "reverseOrder": True,
                "dateColumn": "Date",
                "dateFormat": "%Y-%m-%d",
                "descriptionColumn": "Description",
                "amountMode": "debit_credit",
                "debitColumn": "Debit",
                "creditColumn": "Credit",
                "currency": "USD",
            },
        },
        opening_balance="500.00",
        opening_balance_date="2026-01-01",
    )

    assert account_id == "capital_one_card_4242"
    assert account_cfg["import_profile_id"] == account_id

    reloaded = load_config(workspace_root / "settings" / "workspace.toml")
    assert sorted(reloaded.import_accounts) == [account_id]
    assert sorted(reloaded.tracked_accounts) == [account_id]
    assert sorted(reloaded.import_profiles) == [account_id]
    assert reloaded.import_profiles[account_id]["amount_mode"] == "debit_credit"
    assert reloaded.tracked_accounts[account_id]["import_account_id"] == account_id

    opening_file = workspace_root / "opening" / f"{account_id}.journal"
    assert "Liabilities:Cards:Capital One  USD 500.00" in opening_file.read_text(encoding="utf-8")


def test_upsert_custom_import_account_rewrites_existing_journal_postings_to_new_ledger_account(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "app")
    workspace_root = tmp_path / "workspace"
    profile = {
        "displayName": "Capital One CSV",
        "encoding": "utf-8",
        "delimiter": ",",
        "skipRows": 0,
        "skipFooterRows": 0,
        "reverseOrder": True,
        "dateColumn": "Date",
        "dateFormat": "%Y-%m-%d",
        "descriptionColumn": "Description",
        "amountMode": "debit_credit",
        "debitColumn": "Debit",
        "creditColumn": "Credit",
        "currency": "USD",
    }

    manager.bootstrap_workspace(
        workspace_path=workspace_root,
        workspace_name="Test Books",
        base_currency="USD",
        start_year=2026,
        import_accounts=[],
    )

    config = load_config(workspace_root / "settings" / "workspace.toml")
    account_id, _ = manager.upsert_custom_import_account(
        config,
        {
            "displayName": "Capital One Card",
            "ledgerAccount": "Liabilities:Cards:Capital One",
            "last4": "4242",
            "customProfile": profile,
        },
    )

    journal_path = workspace_root / "journals" / "2026.journal"
    journal_path.write_text(
        "2026/03/04 Online Shop\n"
        f"    ; import_account_id: {account_id}\n"
        "    Liabilities:Cards:Capital One  $-83.21\n"
        "    Expenses:Shopping\n",
        encoding="utf-8",
    )

    updated_config = load_config(workspace_root / "settings" / "workspace.toml")
    manager.upsert_custom_import_account(
        updated_config,
        {
            "displayName": "Capital One Card",
            "ledgerAccount": "Liabilities:Cards:Capital One:Travel",
            "last4": "4242",
            "customProfile": profile,
        },
        account_id=account_id,
    )

    updated_journal = journal_path.read_text(encoding="utf-8")
    assert "Liabilities:Cards:Capital One:Travel  $-83.21" in updated_journal
    assert "Liabilities:Cards:Capital One  $-83.21" not in updated_journal

    reloaded = load_config(workspace_root / "settings" / "workspace.toml")
    register = build_account_register(reloaded, account_id)
    assert register["transactionCount"] == 1
    assert register["currentBalance"] == -83.21


def test_upsert_import_account_removes_stale_custom_profile_when_switching_to_supported_template(tmp_path: Path) -> None:
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
    account_id, _ = manager.upsert_custom_import_account(
        config,
        {
            "displayName": "Checking",
            "ledgerAccount": "Assets:Bank:Checking",
            "customProfile": {
                "displayName": "Checking CSV",
                "encoding": "utf-8",
                "delimiter": ",",
                "skipRows": 0,
                "skipFooterRows": 0,
                "reverseOrder": True,
                "dateColumn": "Date",
                "dateFormat": "%Y-%m-%d",
                "descriptionColumn": "Description",
                "amountMode": "signed",
                "amountColumn": "Amount",
                "currency": "USD",
            },
        },
    )

    reloaded = load_config(workspace_root / "settings" / "workspace.toml")
    manager.upsert_import_account(
        reloaded,
        {
            "institutionId": "wells_fargo",
            "displayName": "Checking",
            "ledgerAccount": "Assets:Bank:Checking",
        },
        account_id=account_id,
    )

    switched = load_config(workspace_root / "settings" / "workspace.toml")
    assert account_id in switched.import_accounts
    assert switched.import_accounts[account_id].get("import_profile_id") in {None, ""}
    assert account_id not in switched.import_profiles
    assert switched.import_accounts[account_id]["institution"] == "wells_fargo"


def test_upsert_tracked_account_rewrites_existing_journal_postings_to_new_ledger_account(tmp_path: Path) -> None:
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
    account_id, _ = manager.upsert_tracked_account(
        config,
        {
            "displayName": "Cash Wallet",
            "ledgerAccount": "Assets:Cash:Wallet",
        },
    )

    journal_path = workspace_root / "journals" / "2026.journal"
    journal_path.write_text(
        "2026/03/01 ATM Withdrawal\n"
        "    Assets:Cash:Wallet  $-20.00\n"
        "    Expenses:Cash\n",
        encoding="utf-8",
    )

    updated_config = load_config(workspace_root / "settings" / "workspace.toml")
    manager.upsert_tracked_account(
        updated_config,
        {
            "displayName": "Cash Wallet",
            "ledgerAccount": "Assets:Cash:Primary:Wallet",
        },
        account_id=account_id,
    )

    updated_journal = journal_path.read_text(encoding="utf-8")
    assert "Assets:Cash:Primary:Wallet  $-20.00" in updated_journal
    assert "Assets:Cash:Wallet  $-20.00" not in updated_journal

    reloaded = load_config(workspace_root / "settings" / "workspace.toml")
    register = build_account_register(reloaded, account_id)
    assert register["transactionCount"] == 1
    assert register["currentBalance"] == -20.0


def test_ensure_journal_includes_prepends_standard_include_block(tmp_path: Path) -> None:
    journal_path = tmp_path / "2026.journal"
    journal_path.write_text(
        "; Existing journal\n"
        "include ../rules/13-commodities.dat\n"
        "\n"
        "2026/03/01 Coffee Shop\n"
        "    Assets:Bank:Checking  $-7.50\n"
        "    Expenses:Food\n",
        encoding="utf-8",
    )

    ensure_journal_includes(journal_path)

    content = journal_path.read_text(encoding="utf-8")
    assert content.startswith(
        "include ../rules/10-accounts.dat\n"
        "include ../rules/12-tags.dat\n"
        "include ../rules/13-commodities.dat\n\n"
    )
    assert content.count("include ../rules/13-commodities.dat") == 1
    assert "; Existing journal" in content
    assert "2026/03/01 Coffee Shop" in content


def test_ensure_standard_commodities_file_appends_symbol_format_for_base_currency(tmp_path: Path) -> None:
    commodities_path = tmp_path / "13-commodities.dat"
    commodities_path.write_text(
        "commodity USD\n"
        "\tformat USD1,000.00\n",
        encoding="utf-8",
    )

    ensure_standard_commodities_file(commodities_path, "USD")

    content = commodities_path.read_text(encoding="utf-8")
    assert content.count("commodity USD") == 1
    assert "commodity $" in content
    assert "\tformat $1,000.00" in content
