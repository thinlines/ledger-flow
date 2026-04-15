from __future__ import annotations
import importlib
import pkgutil
from typing import Optional

from .types import Adapter, Translator

_ADAPTERS: dict[str, Adapter] = {}
_TRANSLATORS: dict[str, Translator] = {}


def register_adapter(cls):
    """Class decorator: instantiate and register an Adapter."""
    instance = cls()
    if instance.name in _ADAPTERS:
        raise RuntimeError(f"Duplicate adapter name: {instance.name!r}")
    _ADAPTERS[instance.name] = instance
    return cls


def register_translator(cls):
    """Class decorator: instantiate and register a Translator."""
    instance = cls()
    if instance.name in _TRANSLATORS:
        raise RuntimeError(f"Duplicate translator name: {instance.name!r}")
    _TRANSLATORS[instance.name] = instance
    return cls


def get_adapter(name: str) -> Adapter:
    return _ADAPTERS[name]


def get_translator(name: str) -> Translator:
    return _TRANSLATORS[name]


def list_adapters() -> list[Adapter]:
    return list(_ADAPTERS.values())


def list_translators() -> list[Translator]:
    return list(_TRANSLATORS.values())


def autodetect_adapter(text: str, filename: str) -> Optional[Adapter]:
    """Reserved for future autodetect-on-upload. Walks adapters that define
    a matches() method and returns the unique match, or None if 0 or >1 match.
    """
    hits = []
    for adapter in _ADAPTERS.values():
        matcher = getattr(adapter, "matches", None)
        if matcher is not None and matcher(text, filename):
            hits.append(adapter)
    return hits[0] if len(hits) == 1 else None


def discover() -> None:
    """Import every parsers/implementations/<name> subpackage so that
    @register_adapter and @register_translator decorators execute."""
    from . import implementations
    for _, name, is_pkg in pkgutil.iter_modules(implementations.__path__):
        if is_pkg:
            importlib.import_module(f"{implementations.__name__}.{name}")
