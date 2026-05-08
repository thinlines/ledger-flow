"""Shared payee normalization and similarity scoring.

Used by both the unknowns match-candidate flow (manual_entry_service)
and the reconciliation duplicate-review flow (reconciliation_duplicate_service).
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

PAYEE_NOISE_WORDS = {"manual", "imported", "copy", "online", "mobile"}


def _normalize_payee_token(token: str) -> str:
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("s") and len(token) > 4:
        return token[:-1]
    return token


def normalize_payee(value: str) -> str:
    """Lowercase, strip punctuation, remove noise words, normalize plurals."""
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    tokens = [
        _normalize_payee_token(token)
        for token in normalized.split()
        if token not in PAYEE_NOISE_WORDS
    ]
    return " ".join(tokens)


def payee_similarity(left: str, right: str) -> float:
    """Return 0.0–1.0 similarity between two payee strings.

    Uses token-set ratio with noise-word removal, plural normalization,
    and a single-token SequenceMatcher fallback (≥ 0.92 threshold).
    """
    left_norm = normalize_payee(left)
    right_norm = normalize_payee(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    common = left_tokens & right_tokens
    if common:
        subset_ratio = len(common) / min(len(left_tokens), len(right_tokens))
        coverage_ratio = len(common) / max(len(left_tokens), len(right_tokens))
        if subset_ratio == 1.0:
            return 0.9 + (0.05 * coverage_ratio)
        return 0.7 + (0.2 * coverage_ratio)
    if len(left_tokens) == 1 and len(right_tokens) == 1:
        ratio = SequenceMatcher(None, left_norm, right_norm).ratio()
        return ratio if ratio >= 0.92 else 0.0
    return 0.0
