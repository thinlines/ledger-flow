"""Tests for the search formula parser."""

from __future__ import annotations

from decimal import Decimal

import pytest

from services.search_parser import SearchTerm, parse_search


# ---------------------------------------------------------------------------
# Bare terms (backward compatibility)
# ---------------------------------------------------------------------------


class TestBareTerms:
    def test_single_bare_term(self):
        terms = parse_search("amazon")
        assert len(terms) == 1
        assert terms[0].field == "payee"
        assert terms[0].operator == "contains"
        assert terms[0].value == "amazon"

    def test_multiple_bare_terms(self):
        terms = parse_search("amazon coffee")
        assert len(terms) == 2
        assert all(t.field == "payee" for t in terms)
        assert terms[0].value == "amazon"
        assert terms[1].value == "coffee"

    def test_empty_string(self):
        assert parse_search("") == []

    def test_none_coerced_empty(self):
        # The service passes "" for None, but test robustness.
        assert parse_search("   ") == []


# ---------------------------------------------------------------------------
# Unknown field prefix treated as bare payee term
# ---------------------------------------------------------------------------


class TestUnknownPrefix:
    def test_unknown_field(self):
        terms = parse_search("foo:bar")
        assert len(terms) == 1
        assert terms[0].field == "payee"
        assert terms[0].value == "foo:bar"

    def test_colon_in_payee(self):
        terms = parse_search("amazon:prime")
        assert len(terms) == 1
        assert terms[0].field == "payee"
        assert terms[0].value == "amazon:prime"


# ---------------------------------------------------------------------------
# Amount terms
# ---------------------------------------------------------------------------


class TestAmountTerms:
    def test_greater_than(self):
        terms = parse_search("amount:>100")
        assert len(terms) == 1
        t = terms[0]
        assert t.field == "amount"
        assert t.operator == "gt"
        assert t.value_num == Decimal("100")

    def test_less_than(self):
        terms = parse_search("amount:<50")
        t = terms[0]
        assert t.operator == "lt"
        assert t.value_num == Decimal("50")

    def test_gte(self):
        terms = parse_search("amount:>=200")
        t = terms[0]
        assert t.operator == "gte"
        assert t.value_num == Decimal("200")

    def test_lte(self):
        terms = parse_search("amount:<=75.50")
        t = terms[0]
        assert t.operator == "lte"
        assert t.value_num == Decimal("75.50")

    def test_exact(self):
        terms = parse_search("amount:42")
        t = terms[0]
        assert t.operator == "eq"
        assert t.value_num == Decimal("42")

    def test_range(self):
        terms = parse_search("amount:50..200")
        t = terms[0]
        assert t.operator == "range"
        assert t.value_num == Decimal("50")
        assert t.value_num_end == Decimal("200")

    def test_strip_dollar_and_commas(self):
        terms = parse_search("amount:>$1,000")
        t = terms[0]
        assert t.operator == "gt"
        assert t.value_num == Decimal("1000")

    def test_negative_amount_uses_absolute(self):
        """Negative signs in amount values are stripped — comparisons use abs."""
        terms = parse_search("amount:<-50")
        t = terms[0]
        assert t.operator == "lt"
        assert t.value_num == Decimal("50")

    def test_malformed_amount_falls_to_payee(self):
        terms = parse_search("amount:>abc")
        assert len(terms) == 1
        assert terms[0].field == "payee"
        assert terms[0].value == "amount:>abc"

    def test_amount_empty_value_falls_to_payee(self):
        terms = parse_search("amount:")
        assert len(terms) == 1
        assert terms[0].field == "payee"
        assert terms[0].value == "amount:"

    def test_amount_dollar_only_falls_to_payee(self):
        terms = parse_search("amount:>$")
        assert len(terms) == 1
        assert terms[0].field == "payee"
        assert terms[0].value == "amount:>$"


# ---------------------------------------------------------------------------
# Category terms
# ---------------------------------------------------------------------------


class TestCategoryTerms:
    def test_category_contains(self):
        terms = parse_search("category:groceries")
        t = terms[0]
        assert t.field == "category"
        assert t.operator == "contains"
        assert t.value == "groceries"

    def test_category_partial(self):
        terms = parse_search("category:groc")
        assert terms[0].value == "groc"


# ---------------------------------------------------------------------------
# Date terms
# ---------------------------------------------------------------------------


class TestDateTerms:
    def test_this_month(self):
        terms = parse_search("date:this-month")
        t = terms[0]
        assert t.field == "date"
        assert t.operator == "exact"
        assert t.value == "this-month"

    def test_last_month(self):
        terms = parse_search("date:last-month")
        assert terms[0].value == "last-month"

    def test_this_year(self):
        terms = parse_search("date:this-year")
        assert terms[0].value == "this-year"

    def test_year_month(self):
        terms = parse_search("date:2026-03")
        assert terms[0].value == "2026-03"

    def test_full_date(self):
        terms = parse_search("date:2026-03-15")
        assert terms[0].value == "2026-03-15"


# ---------------------------------------------------------------------------
# Account terms
# ---------------------------------------------------------------------------


class TestAccountTerms:
    def test_account_contains(self):
        terms = parse_search("account:chase")
        t = terms[0]
        assert t.field == "account"
        assert t.operator == "contains"
        assert t.value == "chase"


# ---------------------------------------------------------------------------
# Status terms
# ---------------------------------------------------------------------------


class TestStatusTerms:
    def test_status_cleared(self):
        terms = parse_search("status:cleared")
        t = terms[0]
        assert t.field == "status"
        assert t.operator == "exact"
        assert t.value == "cleared"

    def test_status_pending(self):
        terms = parse_search("status:pending")
        assert terms[0].value == "pending"

    def test_status_unmarked(self):
        terms = parse_search("status:unmarked")
        assert terms[0].value == "unmarked"


# ---------------------------------------------------------------------------
# Payee explicit prefix
# ---------------------------------------------------------------------------


class TestPayeePrefix:
    def test_explicit_payee(self):
        terms = parse_search("payee:amazon")
        t = terms[0]
        assert t.field == "payee"
        assert t.operator == "contains"
        assert t.value == "amazon"


# ---------------------------------------------------------------------------
# Case insensitivity of field names
# ---------------------------------------------------------------------------


class TestCaseInsensitiveFields:
    def test_uppercase_field(self):
        terms = parse_search("Amount:>100")
        assert terms[0].field == "amount"
        assert terms[0].operator == "gt"

    def test_mixed_case(self):
        terms = parse_search("Category:food")
        assert terms[0].field == "category"


# ---------------------------------------------------------------------------
# Combined terms
# ---------------------------------------------------------------------------


class TestCombinedTerms:
    def test_amount_and_category(self):
        terms = parse_search("amount:>50 category:food")
        assert len(terms) == 2
        assert terms[0].field == "amount"
        assert terms[1].field == "category"

    def test_bare_and_formula(self):
        terms = parse_search("amazon amount:>20")
        assert len(terms) == 2
        assert terms[0].field == "payee"
        assert terms[1].field == "amount"

    def test_multiple_fields(self):
        terms = parse_search("amount:>100 category:groceries status:cleared account:chase")
        assert len(terms) == 4
        fields = [t.field for t in terms]
        assert fields == ["amount", "category", "status", "account"]


# ---------------------------------------------------------------------------
# Edge cases: parser never raises
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_only_colon(self):
        terms = parse_search(":")
        assert len(terms) == 1
        assert terms[0].field == "payee"
        assert terms[0].value == ":"

    def test_leading_trailing_spaces(self):
        terms = parse_search("  amazon  ")
        assert len(terms) == 1
        assert terms[0].value == "amazon"

    def test_multiple_spaces_between_terms(self):
        terms = parse_search("amazon   coffee")
        assert len(terms) == 2

    def test_amount_range_malformed(self):
        terms = parse_search("amount:abc..def")
        assert terms[0].field == "payee"

    def test_amount_range_one_side_bad(self):
        terms = parse_search("amount:50..abc")
        assert terms[0].field == "payee"

    def test_status_value_preserved_lower(self):
        terms = parse_search("status:Cleared")
        assert terms[0].value == "cleared"

    def test_numeric_bare_term(self):
        """A bare number without amount: prefix is a payee term."""
        terms = parse_search("12345")
        assert terms[0].field == "payee"
        assert terms[0].value == "12345"
