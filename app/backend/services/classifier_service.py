"""Description-only logistic category rankings, trained on the current journal.

Embeddings stay local (Ollama); neither notebook data nor fitted pickle files
are used. Cache keys include the complete labeled history so edits and undo
invalidate the fit, while unchanged descriptions reuse their embeddings.
"""
from __future__ import annotations

from collections import OrderedDict
from functools import lru_cache
import logging
from time import monotonic

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from . import ollama_service
from .config_service import AppConfig
from .journal_query_service import ParsedTransaction, is_uncategorized
from .priority_lock import PriorityLock
from .projection_service import load_transactions_projected

_LOG = logging.getLogger(__name__)

# nomic-embed-text is prefix-conditioned: the task prefix belongs to this
# classifier, not to the provider. Cached vectors are keyed by the unprefixed
# description, which is safe only while one prefix is in use.
_EMBED_PREFIX = "classification: description: "
_VECTOR_CACHE_SIZE = 10000
# How much warmup embeds before releasing the lock to any waiting review request.
_WARMUP_BATCH = 32
_COOLDOWN_SECONDS = 30

_LOCK = PriorityLock()
_retry_after: dict[str, float] = {}

# Accessed under _LOCK. Keep only frozen vectors, never fitted pickle files.
_vectors: OrderedDict[str, tuple[float, ...]] = OrderedDict()


def _embed_many(descriptions: list[str]) -> list[tuple[float, ...]]:
    missing = list(dict.fromkeys(text for text in descriptions if text not in _vectors))
    # Keep this request's vectors even if its history exceeds the shared cache.
    available = {text: _vectors[text] for text in descriptions if text in _vectors}
    if missing:
        available.update(zip(missing, ollama_service.embed([_EMBED_PREFIX + text for text in missing])))
    for text, vector in available.items():
        _vectors[text] = vector
        _vectors.move_to_end(text)
    while len(_vectors) > _VECTOR_CACHE_SIZE:
        _vectors.popitem(last=False)
    return [available[text] for text in descriptions]


def _training_rows(config: AppConfig) -> tuple[tuple[str, str], ...]:
    return _labeled_rows(load_transactions_projected(config))


def _labeled_rows(transactions: list[ParsedTransaction]) -> tuple[tuple[str, str], ...]:
    rows = []
    for txn in transactions:
        # Partial categorization and splits are ambiguous single-label examples.
        if is_uncategorized(txn):
            continue
        categories = {p.account for p in txn.postings if p.account.startswith(("Expenses:", "Income:"))}
        if txn.payee.strip() and len(categories) == 1:
            rows.append((txn.payee.strip(), next(iter(categories))))
    return tuple(sorted(rows))


def _unresolved_payees(transactions: list[ParsedTransaction]) -> list[str]:
    """Deduplicated payees of transactions Review has yet to categorize."""
    return list(dict.fromkeys(
        txn.payee.strip() for txn in transactions
        if txn.payee.strip() and is_uncategorized(txn)
    ))


@lru_cache(maxsize=4)
def _fit(workspace: str, rows: tuple[tuple[str, str], ...]):
    model = make_pipeline(StandardScaler(), LogisticRegression(
        class_weight="balanced", max_iter=1000, random_state=0,
    ))
    model.fit(np.asarray(_embed_many([payee for payee, _ in rows])), [category for _, category in rows])
    return model


def suggest_review_categories(payee: str, config: AppConfig) -> dict:
    empty = {"suggestions": [], "status": "insufficient_history"}
    if not payee.strip():
        return empty
    rows = _training_rows(config)
    if len({category for _, category in rows}) < 2:
        return empty
    workspace = str(config.root_dir.resolve())
    with _LOCK.access():
        if monotonic() < _retry_after.get(workspace, 0):
            return {"suggestions": [], "status": "unavailable"}
        try:
            model = _fit(workspace, rows)
            probabilities = model.predict_proba(_embed_many([payee.strip()]))[0]
            ranked = sorted(zip(model.classes_, probabilities), key=lambda pair: (-pair[1], pair[0]))[:3]
            return {"suggestions": [
                {"account": str(account), "probability": float(probability)}
                for account, probability in ranked
            ], "status": "ready"}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            _retry_after[workspace] = monotonic() + _COOLDOWN_SECONDS
            _LOG.warning("Category classifier unavailable: %s", type(exc).__name__)
            return {"suggestions": [], "status": "unavailable"}


def _warm_embeddings(payees: list[str]) -> None:
    """Cache vectors a batch at a time, releasing the lock between batches."""
    for offset in range(0, len(payees), _WARMUP_BATCH):
        with _LOCK.access(background=True):
            _embed_many(payees[offset:offset + _WARMUP_BATCH])


def warm_review_classifier(config: AppConfig) -> None:
    """Prepare current history and unresolved payees without persisting predictions.

    Called by the background worker after import commits. Work is split so that
    queued interactive requests take priority between batches. A history
    snapshot keys the fit; subsequent edits/undo use a different key.
    """
    workspace = str(config.root_dir.resolve())
    try:
        with _LOCK.access(background=True):
            if monotonic() < _retry_after.get(workspace, 0):
                return
        transactions = load_transactions_projected(config)
        rows = _labeled_rows(transactions)
        if len({category for _, category in rows}) < 2:
            return
        _warm_embeddings(list(dict.fromkeys(payee for payee, _ in rows)))
        with _LOCK.access(background=True):
            _fit(workspace, rows)
        _warm_embeddings(_unresolved_payees(transactions))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        with _LOCK.access(background=True):
            _retry_after[workspace] = monotonic() + _COOLDOWN_SECONDS
        _LOG.warning("Category classifier warmup unavailable: %s", type(exc).__name__)
