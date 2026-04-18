"""Tests for institution_registry derivation from adapter registry.

Verifies that _build_registry() produces identical InstitutionTemplate entries
from adapter class attributes + legacy bridges (Schwab, BJB).
"""

from __future__ import annotations

import pytest

from services.institution_registry import (
    InstitutionTemplate,
    _REGISTRY,
    canonical_template_id,
    get_template,
    list_templates,
)


class TestRegistryContents:
    """All five institutions present with correct field values."""

    def test_list_templates_count(self):
        templates = list(_REGISTRY.values())
        assert len(templates) == 5

    def test_all_ids_present(self):
        ids = sorted(_REGISTRY.keys())
        assert ids == ["alipay", "bank_of_beijing", "charles_schwab", "icbc", "wells_fargo"]

    def test_wells_fargo_fields(self):
        t = _REGISTRY["wells_fargo"]
        assert t.id == "wells_fargo"
        assert t.display_name == "Wells Fargo"
        assert t.parser == "wells_fargo"
        assert t.csv_date_format == "%m/%d/%Y"
        assert t.suggested_ledger_prefix == "Assets:Bank:Wells Fargo"
        assert t.aliases == ("wfchk", "wfsav", "wfcc", "wells-fargo", "wellsfargo")
        assert t.head == 0
        assert t.tail == 0
        assert t.encoding == "utf-8"

    def test_alipay_fields(self):
        t = _REGISTRY["alipay"]
        assert t.id == "alipay"
        assert t.display_name == "Alipay"
        assert t.parser == "alipay"
        assert t.csv_date_format == "%Y-%m-%d"
        assert t.suggested_ledger_prefix == "Assets:Alipay"
        assert t.aliases == ("alipay",)
        assert t.head == 13
        assert t.tail == 1
        assert t.encoding == "GB18030"

    def test_icbc_fields(self):
        t = _REGISTRY["icbc"]
        assert t.id == "icbc"
        assert t.display_name == "Industrial and Commercial Bank of China"
        assert t.parser == "icbc"
        assert t.csv_date_format == "%Y-%m-%d"
        assert t.suggested_ledger_prefix == "Assets:Bank:ICBC"
        assert t.aliases == ("icbc",)
        assert t.head == 7
        assert t.tail == 2
        assert t.encoding == "utf-8"

    def test_schwab_bridge_fields(self):
        t = _REGISTRY["charles_schwab"]
        assert t.id == "charles_schwab"
        assert t.display_name == "Charles Schwab"
        assert t.parser == "schwab"
        assert t.csv_date_format == "%m/%d/%Y"
        assert t.suggested_ledger_prefix == "Assets:Investments:Schwab"
        assert t.aliases == ("schwab",)

    def test_bjb_bridge_fields(self):
        t = _REGISTRY["bank_of_beijing"]
        assert t.id == "bank_of_beijing"
        assert t.display_name == "Bank of Beijing"
        assert t.parser == "bjb"
        assert t.csv_date_format == "%Y/%m/%d"
        assert t.suggested_ledger_prefix == "Assets:Bank:BJB"
        assert t.aliases == ("bjb", "beijing-bank", "bank-of-beijing")
        assert t.head == 1
        assert t.tail == 0


class TestAliasResolution:
    """Aliases from adapter class attributes and legacy bridges resolve correctly."""

    def test_wells_fargo_alias_wfchk(self):
        assert canonical_template_id("wfchk") == "wells_fargo"

    def test_wells_fargo_alias_wfsav(self):
        assert canonical_template_id("wfsav") == "wells_fargo"

    def test_wells_fargo_alias_wfcc(self):
        assert canonical_template_id("wfcc") == "wells_fargo"

    def test_wells_fargo_alias_dash(self):
        assert canonical_template_id("wells-fargo") == "wells_fargo"

    def test_wells_fargo_alias_nospace(self):
        assert canonical_template_id("wellsfargo") == "wells_fargo"

    def test_schwab_bridge_alias(self):
        assert canonical_template_id("schwab") == "charles_schwab"

    def test_bjb_bridge_alias(self):
        assert canonical_template_id("bjb") == "bank_of_beijing"

    def test_bjb_bridge_alias_dash(self):
        assert canonical_template_id("beijing-bank") == "bank_of_beijing"

    def test_bjb_bridge_alias_bank_of_beijing(self):
        assert canonical_template_id("bank-of-beijing") == "bank_of_beijing"

    def test_alipay_alias(self):
        assert canonical_template_id("alipay") == "alipay"

    def test_icbc_alias(self):
        assert canonical_template_id("icbc") == "icbc"

    def test_case_insensitive(self):
        assert canonical_template_id("WFCHK") == "wells_fargo"
        assert canonical_template_id("Schwab") == "charles_schwab"

    def test_unknown_returns_none(self):
        assert canonical_template_id("nonexistent") is None


class TestEncodingHeadTail:
    """Adapter-derived metadata preserved through the derivation pipeline."""

    def test_alipay_encoding(self):
        t = get_template("alipay")
        assert t is not None
        assert t.encoding == "GB18030"

    def test_alipay_head(self):
        t = get_template("alipay")
        assert t is not None
        assert t.head == 13

    def test_alipay_tail(self):
        t = get_template("alipay")
        assert t is not None
        assert t.tail == 1

    def test_icbc_head(self):
        t = get_template("icbc")
        assert t is not None
        assert t.head == 7

    def test_icbc_tail(self):
        t = get_template("icbc")
        assert t is not None
        assert t.tail == 2

    def test_wells_fargo_defaults(self):
        t = get_template("wells_fargo")
        assert t is not None
        assert t.head == 0
        assert t.tail == 0
        assert t.encoding == "utf-8"


class TestCollisionDetection:
    """_build_registry() raises RuntimeError on slug collisions."""

    def test_institution_slug_collision_with_legacy_bridge(self):
        from services.parsers import registry as parsers_registry

        class _FakeCollidingAdapter:
            name = "fake_schwab"
            institution = "charles_schwab"
            formats = ("csv",)
            translator_name = "generic.checking"
            display_name = "Fake Schwab"
            csv_date_format = "%m/%d/%Y"
            suggested_ledger_prefix = "Assets:Fake"
            aliases = ()
            head = 0
            tail = 0
            encoding = "utf-8"

        # Manually register the colliding adapter.
        instance = _FakeCollidingAdapter()
        parsers_registry._ADAPTERS[instance.name] = instance
        try:
            from services.institution_registry import _build_registry
            with pytest.raises(RuntimeError, match="Institution slug collision"):
                _build_registry()
        finally:
            del parsers_registry._ADAPTERS[instance.name]


class TestPublicAPI:
    """Public function signatures and return shapes are preserved."""

    def test_list_templates_returns_list_of_dicts(self):
        result = list_templates()
        assert isinstance(result, list)
        assert len(result) == 5
        for item in result:
            assert isinstance(item, dict)
            assert "id" in item
            assert "displayName" in item
            assert "suggestedLedgerPrefix" in item

    def test_list_templates_sorted_by_display_name(self):
        result = list_templates()
        names = [item["displayName"] for item in result]
        assert names == sorted(names)

    def test_get_template_returns_institution_template(self):
        result = get_template("wells_fargo")
        assert isinstance(result, InstitutionTemplate)

    def test_get_template_unknown_returns_none(self):
        result = get_template("nonexistent")
        assert result is None
