from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InstitutionTemplate:
    id: str
    display_name: str
    account: str
    csv_date_format: str
    head: int | None = None
    tail: int | None = None
    encoding: str | None = None

    def as_config(self) -> dict:
        payload: dict[str, str | int] = {
            "display_name": self.display_name,
            "account": self.account,
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
        return {"id": self.id, "displayName": self.display_name}


_REGISTRY: dict[str, InstitutionTemplate] = {
    "wfchk": InstitutionTemplate(
        id="wfchk",
        display_name="Wells Fargo Checking",
        account="Assets:Bank:Checking",
        csv_date_format="%m/%d/%Y",
    ),
    "wfsav": InstitutionTemplate(
        id="wfsav",
        display_name="Wells Fargo Savings",
        account="Assets:Bank:Savings",
        csv_date_format="%m/%d/%Y",
    ),
    "wfcc": InstitutionTemplate(
        id="wfcc",
        display_name="Wells Fargo Credit Card",
        account="Liabilities:Credit Card",
        csv_date_format="%m/%d/%Y",
    ),
    "schwab": InstitutionTemplate(
        id="schwab",
        display_name="Charles Schwab",
        account="Assets:Investments:Schwab",
        csv_date_format="%m/%d/%Y",
    ),
    "icbc": InstitutionTemplate(
        id="icbc",
        display_name="Industrial and Commercial Bank of China",
        account="Assets:Bank:ICBC",
        csv_date_format="%Y-%m-%d",
        head=7,
        tail=2,
    ),
    "alipay": InstitutionTemplate(
        id="alipay",
        display_name="Alipay",
        account="Assets:Alipay",
        csv_date_format="%Y-%m-%d",
        head=13,
        tail=1,
        encoding="GB18030",
    ),
    "bjb": InstitutionTemplate(
        id="bjb",
        display_name="Bank of Beijing",
        account="Assets:Bank:BJB",
        csv_date_format="%Y/%m/%d",
        head=1,
        tail=0,
    ),
}


def get_template(template_id: str) -> InstitutionTemplate | None:
    return _REGISTRY.get(template_id)


def list_templates() -> list[dict]:
    return [tpl.as_ui() for tpl in sorted(_REGISTRY.values(), key=lambda x: x.display_name)]


def display_name_for(template_id: str, fallback: str | None = None) -> str:
    tpl = get_template(template_id)
    if tpl:
        return tpl.display_name
    return fallback or template_id
