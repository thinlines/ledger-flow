"""Category suggestion service.

Two-pass prediction for transaction category (destination account):
  1. Deterministic rule match via rules_service
  2. Statistical journal frequency weighted by payee similarity
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from .config_service import AppConfig
from .journal_query_service import ParsedTransaction, get_transactions_cached
from .payee_similarity import normalize_payee, payee_similarity
from .rules_service import ensure_rules_store, extract_set_account, find_matching_rule, load_rules

# Category posting prefixes — these are the "destination" side of a transaction,
# as opposed to the "source" side (Assets/Liabilities = bank/tracked accounts).
_CATEGORY_PREFIXES = ("Expenses:", "Income:", "Equity:")

# ---------------------------------------------------------------------------
# Frequency-map cache (mtime-based invalidation, same pattern as _tx_cache)
# ---------------------------------------------------------------------------

_freq_cache: dict[str, dict[str, int]] | None = None
_freq_cache_mtime: float | None = None
_freq_cache_lock = threading.Lock()


def _is_category_account(account: str) -> bool:
    """Return True if the account looks like a category (not a bank/tracked account)."""
    return any(account.startswith(prefix) for prefix in _CATEGORY_PREFIXES)


def _build_frequency_map(transactions: list[ParsedTransaction]) -> dict[str, dict[str, int]]:
    """Build {normalized_payee: {category_account: count}} from parsed transactions."""
    freq: dict[str, dict[str, int]] = {}
    for txn in transactions:
        norm = normalize_payee(txn.payee)
        if not norm:
            continue
        for posting in txn.postings:
            if _is_category_account(posting.account):
                bucket = freq.setdefault(norm, {})
                bucket[posting.account] = bucket.get(posting.account, 0) + 1
    return freq


def _get_frequency_map(config: AppConfig) -> dict[str, dict[str, int]]:
    """Return the frequency map, rebuilding only when journal files change."""
    max_mtime = max(
        (os.path.getmtime(p) for p in config.journal_dir.glob("*.journal") if p.exists()),
        default=0.0,
    )
    with _freq_cache_lock:
        global _freq_cache, _freq_cache_mtime
        if _freq_cache is None or max_mtime != _freq_cache_mtime:
            _freq_cache = _build_frequency_map(get_transactions_cached(config))
            _freq_cache_mtime = max_mtime
        return _freq_cache


def suggest_category(payee: str, config: AppConfig) -> dict:
    """Suggest a category for the given payee.

    Returns:
        {
            "suggestion": str | None,  # top category account
            "confidence": float,       # 0.0-1.0
            "source": str | None,      # "rule" | "history"
            "alternatives": list[dict]  # [{"account": str, "frequency": int}, ...]
        }
    """
    empty = {"suggestion": None, "confidence": 0.0, "source": None, "alternatives": []}

    if not payee.strip():
        return empty

    # ------------------------------------------------------------------
    # Pass 1 — Deterministic rule match
    # ------------------------------------------------------------------
    accounts_dat = config.init_dir / "10-accounts.dat"
    rules_file = ensure_rules_store(config.init_dir, accounts_dat)
    rules = load_rules(rules_file)
    matched_rule = find_matching_rule({"payee": payee}, rules)
    if matched_rule is not None:
        account = extract_set_account(matched_rule)
        if account:
            return {
                "suggestion": account,
                "confidence": 1.0,
                "source": "rule",
                "alternatives": [],
            }

    # ------------------------------------------------------------------
    # Pass 2 — Journal frequency weighted by payee similarity
    # ------------------------------------------------------------------
    freq_map = _get_frequency_map(config)
    if not freq_map:
        return empty

    # Aggregate category frequencies across similar payees
    aggregated: dict[str, float] = {}
    for known_payee, categories in freq_map.items():
        sim = payee_similarity(payee, known_payee)
        if sim < 0.6:
            continue
        for account, count in categories.items():
            aggregated[account] = aggregated.get(account, 0.0) + count * sim

    if not aggregated:
        return empty

    # Sort by weighted frequency descending
    ranked = sorted(aggregated.items(), key=lambda item: item[1], reverse=True)
    top_account, top_score = ranked[0]

    # Confidence: ratio of top score to total
    total = sum(score for _, score in ranked)
    confidence = round(top_score / total, 4) if total > 0 else 0.0

    # Top 3 alternatives (excluding the top suggestion)
    alternatives = [
        {"account": account, "frequency": round(score, 2)}
        for account, score in ranked[1:4]
    ]

    return {
        "suggestion": top_account,
        "confidence": confidence,
        "source": "history",
        "alternatives": alternatives,
    }
