from __future__ import annotations

from dataclasses import dataclass

from .parsers import registry as parsers_registry


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


# BJB stays as a hardcoded bridge entry until Task 07 Commit B deletes it.
# Out of scope for the CSV parser refactor (YAGNI per 2026-04-15 scope trim).
# See memory project_csv_parser_refactor.md.
_LEGACY_BRIDGES: tuple[InstitutionTemplate, ...] = (
    InstitutionTemplate(
        id="bank_of_beijing",
        display_name="Bank of Beijing",
        parser="bjb",
        csv_date_format="%Y/%m/%d",
        suggested_ledger_prefix="Assets:Bank:BJB",
        aliases=("bjb", "beijing-bank", "bank-of-beijing"),
        head=1,
        tail=0,
    ),
)


def _build_registry() -> dict[str, InstitutionTemplate]:
    """Construct the institution registry from registered adapters + legacy bridges.

    Adapters provide presentation metadata via class attributes (display_name,
    csv_date_format, suggested_ledger_prefix, aliases, head, tail, encoding).
    Legacy bridges (BJB) are hardcoded until removed.
    """
    parsers_registry.discover()
    out: dict[str, InstitutionTemplate] = {b.id: b for b in _LEGACY_BRIDGES}

    # Track all aliases for collision detection.
    seen_aliases: dict[str, str] = {}
    for bridge in _LEGACY_BRIDGES:
        for alias in (bridge.id, *bridge.aliases):
            seen_aliases[alias.lower()] = bridge.id

    for adapter in parsers_registry.list_adapters():
        if adapter.institution in out:
            raise RuntimeError(
                f"Institution slug collision: {adapter.institution!r} already "
                f"declared by a legacy bridge"
            )

        # Check for alias collisions across institutions.
        adapter_aliases = tuple(adapter.aliases)
        for alias in (adapter.institution, *adapter_aliases):
            lower = alias.lower()
            if lower in seen_aliases and seen_aliases[lower] != adapter.institution:
                raise RuntimeError(
                    f"Alias collision: {alias!r} claimed by both "
                    f"{seen_aliases[lower]!r} and {adapter.institution!r}"
                )
            seen_aliases[lower] = adapter.institution

        out[adapter.institution] = InstitutionTemplate(
            id=adapter.institution,
            display_name=adapter.display_name,
            parser=adapter.name,
            csv_date_format=adapter.csv_date_format,
            suggested_ledger_prefix=adapter.suggested_ledger_prefix,
            aliases=adapter_aliases,
            head=int(adapter.head),
            tail=int(adapter.tail),
            encoding=str(adapter.encoding),
        )
    return out


_REGISTRY: dict[str, InstitutionTemplate] = _build_registry()

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
