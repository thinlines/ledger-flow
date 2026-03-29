from services.header_parser import (
    ParsedHeader,
    TransactionStatus,
    parse_header,
    set_header_status,
)


def test_parse_cleared_with_payee():
    result = parse_header("2026/01/15 * UBER TRIP")
    assert result == ParsedHeader(
        date="2026/01/15",
        status=TransactionStatus.cleared,
        code=None,
        payee="UBER TRIP",
    )


def test_parse_pending():
    result = parse_header("2026/03/01 ! Rent payment")
    assert result is not None
    assert result.status == TransactionStatus.pending
    assert result.payee == "Rent payment"


def test_parse_unmarked():
    result = parse_header("2026/03/28 Coffee Shop")
    assert result is not None
    assert result.status == TransactionStatus.unmarked
    assert result.payee == "Coffee Shop"


def test_parse_with_code():
    result = parse_header("2026/01/15 * (1234) UBER")
    assert result is not None
    assert result.status == TransactionStatus.cleared
    assert result.code == "(1234)"
    assert result.payee == "UBER"


def test_parse_empty_payee():
    result = parse_header("2026/01/15 *")
    assert result is not None
    assert result.status == TransactionStatus.cleared
    assert result.payee == ""


def test_parse_dash_date():
    result = parse_header("2026-01-15 * Groceries")
    assert result is not None
    assert result.date == "2026-01-15"
    assert result.status == TransactionStatus.cleared


def test_parse_invalid():
    assert parse_header("not a header") is None
    assert parse_header("") is None


def test_set_status_unmarked_to_pending():
    line = "2026/03/28 Coffee Shop"
    result = set_header_status(line, TransactionStatus.pending)
    assert result == "2026/03/28 ! Coffee Shop"


def test_set_status_pending_to_cleared():
    line = "2026/03/28 ! Coffee Shop"
    result = set_header_status(line, TransactionStatus.cleared)
    assert result == "2026/03/28 * Coffee Shop"


def test_set_status_cleared_to_unmarked():
    line = "2026/03/28 * Coffee Shop"
    result = set_header_status(line, TransactionStatus.unmarked)
    assert result == "2026/03/28 Coffee Shop"


def test_set_status_preserves_code():
    line = "2026/01/15 * (1234) UBER"
    result = set_header_status(line, TransactionStatus.unmarked)
    assert result == "2026/01/15 (1234) UBER"


def test_set_status_empty_payee():
    line = "2026/01/15 *"
    result = set_header_status(line, TransactionStatus.unmarked)
    assert result == "2026/01/15"


def test_set_status_invalid_returns_original():
    line = "not a header"
    assert set_header_status(line, TransactionStatus.cleared) == line


def test_roundtrip_all_statuses():
    base = "2026/01/15 (CODE) My Payee"
    for status in TransactionStatus:
        rewritten = set_header_status(base, status)
        parsed = parse_header(rewritten)
        assert parsed is not None
        assert parsed.status == status
        assert parsed.code == "(CODE)"
        assert parsed.payee == "My Payee"
