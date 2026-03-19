import csv
import io
from pathlib import Path

from services.config_service import AppConfig
from services.csv_normalizer import normalize_csv_to_intermediate
from services.custom_csv_service import inspect_csv_bytes, normalize_custom_csv_to_intermediate


def test_inspect_csv_bytes_detects_delimiter_and_headers() -> None:
    content = (
        "Transaction Date;Merchant;Amount;Balance\n"
        "03/05/2026;Coffee Shop;-7.50;992.50\n"
        "03/04/2026;Payroll;2000.00;1000.00\n"
    ).encode("utf-8")

    inspected = inspect_csv_bytes(content)

    assert inspected["delimiter"] == ";"
    assert inspected["headers"] == ["Transaction Date", "Merchant", "Amount", "Balance"]
    assert inspected["sampleRows"][0]["Merchant"] == "Coffee Shop"


def test_normalize_custom_csv_to_intermediate_handles_signed_amounts(tmp_path: Path) -> None:
    csv_path = tmp_path / "statement.csv"
    csv_path.write_text(
        "Transaction Date,Merchant,Amount,Balance\n"
        "03/05/2026,Coffee Shop,-7.50,992.50\n"
        "03/04/2026,Payroll,2000.00,1000.00\n",
        encoding="utf-8",
    )

    out = normalize_custom_csv_to_intermediate(
        csv_path,
        {
            "display_name": "Checking CSV",
            "encoding": "utf-8",
            "delimiter": ",",
            "skip_rows": 0,
            "skip_footer_rows": 0,
            "reverse_order": True,
            "date_column": "Transaction Date",
            "date_format": "%m/%d/%Y",
            "description_column": "Merchant",
            "secondary_description_column": None,
            "amount_mode": "signed",
            "amount_column": "Amount",
            "debit_column": None,
            "credit_column": None,
            "balance_column": "Balance",
            "code_column": None,
            "note_column": None,
            "currency": "$",
        },
    )

    assert "2026/03/04,,Payroll,$2000.00,$1000.00" in out
    assert "2026/03/05,,Coffee Shop,$-7.50,$992.50" in out


def test_normalize_csv_to_intermediate_uses_account_profile_for_custom_accounts(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    for rel in ["settings", "journals", "inbox", "rules", "opening", "imports"]:
        (workspace / rel).mkdir(parents=True, exist_ok=True)

    csv_path = workspace / "inbox" / "2026__capital_one__statement.csv"
    csv_path.write_text(
        "Date,Description,Debit,Credit\n"
        "2026-03-05,Coffee Shop,7.50,\n"
        "2026-03-04,Refund,,12.00\n",
        encoding="utf-8",
    )

    config = AppConfig(
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
            "capital_one": {
                "display_name": "Capital One Card",
                "ledger_account": "Liabilities:Cards:Capital One",
                "import_profile_id": "capital_one",
            }
        },
        import_profiles={
            "capital_one": {
                "kind": "custom_csv",
                "display_name": "Capital One CSV",
                "encoding": "utf-8",
                "delimiter": ",",
                "skip_rows": 0,
                "skip_footer_rows": 0,
                "reverse_order": True,
                "date_column": "Date",
                "date_format": "%Y-%m-%d",
                "description_column": "Description",
                "amount_mode": "debit_credit",
                "debit_column": "Debit",
                "credit_column": "Credit",
                "currency": "$",
            }
        },
    )

    out = normalize_csv_to_intermediate(config, csv_path, config.import_accounts["capital_one"])

    assert "2026/03/04,,Refund,$12.00" in out
    assert "2026/03/05,,Coffee Shop,$-7.50" in out


def test_normalize_csv_to_intermediate_reverses_newest_first_institution_rows(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    for rel in ["settings", "journals", "inbox", "rules", "opening", "imports"]:
        (workspace / rel).mkdir(parents=True, exist_ok=True)

    csv_path = workspace / "inbox" / "2026__wf_checking__statement.csv"
    csv_path.write_text(
        '"03/12/2026","1984.86","*","","ONLINE PAYMENT THANK YOU"\n'
        '"03/12/2026","-7.10","*","","TC @ ALBERTSONS CORPORAT BOISE ID"\n'
        '"03/12/2026","-98.56","*","","AMAZON MKTPL*BP9TA8360 Amzn.com/billWA"\n',
        encoding="utf-8",
    )

    config = AppConfig(
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
                "display_name": "Wells Fargo",
                "parser": "wfchk",
                "CSV_date_format": "%Y/%m/%d",
            }
        },
        import_accounts={
            "wf_checking": {
                "display_name": "Wells Fargo Checking",
                "institution": "wells_fargo",
                "ledger_account": "Assets:Bank:Checking",
            }
        },
        payee_aliases="payee_aliases.csv",
    )

    out = normalize_csv_to_intermediate(config, csv_path, config.import_accounts["wf_checking"])
    rows = list(csv.DictReader(io.StringIO(out)))

    assert [row["description"] for row in rows] == [
        "AMAZON MKTPL*BP9TA8360 Amzn.com/billWA",
        "TC @ ALBERTSONS CORPORAT BOISE ID",
        "ONLINE PAYMENT THANK YOU",
    ]
