"""Description-only logistic category rankings, trained on the current journal.

Embeddings stay local (Ollama); neither notebook data nor fitted pickle files
are used. Cache keys include the complete labeled history so edits and undo
invalidate the fit, while unchanged descriptions reuse their embeddings.
"""
from __future__ import annotations

from collections import OrderedDict
from functools import lru_cache
import json
import logging
from threading import Lock
from time import monotonic
import urllib.request

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .config_service import AppConfig
from .projection_service import load_transactions_projected

_LOG = logging.getLogger(__name__)
_LOCK = Lock()
_retry_after: dict[str, float] = {}


# Accessed under _LOCK. Keep only frozen vectors, never fitted pickle files.
_vectors: OrderedDict[str, tuple[float, ...]] = OrderedDict()


def _embed_many(descriptions: list[str]) -> list[tuple[float, ...]]:
    missing = list(dict.fromkeys(text for text in descriptions if text not in _vectors))
    # Keep this request's vectors even if its history exceeds the shared cache.
    available = {text: _vectors[text] for text in descriptions if text in _vectors}
    for offset in range(0, len(missing), 32):
        batch = missing[offset:offset + 32]
        request = urllib.request.Request(
            "http://127.0.0.1:11434/api/embed",
            data=json.dumps({"model": "nomic-embed-text", "input": [
                f"classification: description: {text}" for text in batch
            ]}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            vectors = np.asarray(json.load(response)["embeddings"], dtype=np.float32)
        if vectors.ndim != 2 or len(vectors) != len(batch) or not vectors.shape[1] or not np.isfinite(vectors).all():
            raise ValueError("Invalid embedding response")
        available.update((text, tuple(vector)) for text, vector in zip(batch, vectors))
    for text, vector in available.items():
        _vectors[text] = vector
        _vectors.move_to_end(text)
    while len(_vectors) > 10000:
        _vectors.popitem(last=False)
    return [available[text] for text in descriptions]


def _training_rows(config: AppConfig) -> tuple[tuple[str, str], ...]:
    rows = []
    for txn in load_transactions_projected(config):
        # Partial categorization and splits are ambiguous single-label examples.
        if any(p.account.casefold().endswith(":unknown") for p in txn.postings):
            continue
        categories = {p.account for p in txn.postings if p.account.startswith(("Expenses:", "Income:"))}
        if txn.payee.strip() and len(categories) == 1:
            rows.append((txn.payee.strip(), next(iter(categories))))
    return tuple(sorted(rows))


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
    with _LOCK:
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
            _retry_after[workspace] = monotonic() + 30
            _LOG.warning("Category classifier unavailable: %s", type(exc).__name__)
            return {"suggestions": [], "status": "unavailable"}
