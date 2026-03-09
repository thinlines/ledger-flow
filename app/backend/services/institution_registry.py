from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InstitutionTemplate:
    id: str
    display_name: str
    parser: str
    csv_date_format: str
    suggested_ledger_prefix: str
    aliases: tuple[str, ...] = ()
    head: int | None = None
    tail: int | None = None
    encoding: str | None = None

    def as_config(self) -> dict:
        payload: dict[str, str | int] = {
            "display_name": self.display_name,
            "parser": self.parser,
            "CSV_date_format": self.csv_date_format,
        }
        if self.head is not None:
            payload["head"] = self.head
        if self.tail is not None:
            payload["tail"] = self.tail
        if self.encoding is not None:
            payload["encoding"] = self.encoding
        return payload

    def as_ui(self) -> dict:
        return {
            "id": self.id,
            "displayName": self.display_name,
            "suggestedLedgerPrefix": self.suggested_ledger_prefix,
        }


_REGISTRY: dict[str, InstitutionTemplate] = {
    "wells_fargo": InstitutionTemplate(
        id="wells_fargo",
        display_name="Wells Fargo",
        parser="wfchk",
        csv_date_format="%m/%d/%Y",
        suggested_ledger_prefix="Assets:Bank:Wells Fargo",
        aliases=("wfchk", "wfsav", "wfcc", "wells-fargo", "wellsfargo"),
    ),
    "charles_schwab": InstitutionTemplate(
        id="charles_schwab",
        display_name="Charles Schwab",
        parser="schwab",
        csv_date_format="%m/%d/%Y",
        suggested_ledger_prefix="Assets:Investments:Schwab",
        aliases=("schwab",),
    ),
    "icbc": InstitutionTemplate(
        id="icbc",
        display_name="Industrial and Commercial Bank of China",
        parser="icbc",
        csv_date_format="%Y-%m-%d",
        suggested_ledger_prefix="Assets:Bank:ICBC",
        aliases=("icbc",),
        head=7,
        tail=2,
    ),
    "alipay": InstitutionTemplate(
        id="alipay",
        display_name="Alipay",
        parser="alipay",
        csv_date_format="%Y-%m-%d",
        suggested_ledger_prefix="Assets:Alipay",
        aliases=("alipay",),
        head=13,
        tail=1,
        encoding="GB18030",
    ),
    "bank_of_beijing": InstitutionTemplate(
        id="bank_of_beijing",
        display_name="Bank of Beijing",
        parser="bjb",
        csv_date_format="%Y/%m/%d",
        suggested_ledger_prefix="Assets:Bank:BJB",
        aliases=("bjb", "beijing-bank", "bank-of-beijing"),
        head=1,
        tail=0,
    ),
}

_ALIAS_TO_ID: dict[str, str] = {}
for _id, _tpl in _REGISTRY.items():
    _ALIAS_TO_ID[_id] = _id
    for _alias in _tpl.aliases:
        _ALIAS_TO_ID[_alias.lower()] = _id


def get_template(template_id: str) -> InstitutionTemplate | None:
    return _REGISTRY.get(template_id)


def list_templates() -> list[dict]:
    return [tpl.as_ui() for tpl in sorted(_REGISTRY.values(), key=lambda x: x.display_name)]


def display_name_for(template_id: str, fallback: str | None = None) -> str:
    canonical = canonical_template_id(template_id) or template_id
    tpl = get_template(canonical)
    if tpl:
        return tpl.display_name
    return fallback or template_id


def canonical_template_id(raw_id: str | None) -> str | None:
    if not raw_id:
        return None
    return _ALIAS_TO_ID.get(raw_id.lower())
