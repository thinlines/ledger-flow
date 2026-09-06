"""The local Ollama embedding endpoint: the one place that speaks its protocol.

Callers ask for vectors and, separately, for the model to stay resident. The
request envelope, batch size, timeout, residency lease, and response schema are
implementation details of this module; nothing outside it builds an Ollama
request. See https://docs.ollama.com/api/embed.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import logging
from threading import Event, Thread
import urllib.request

import numpy as np

_EMBED_URL = "http://127.0.0.1:11434/api/embed"
_EMBED_MODEL = "nomic-embed-text"
# Ollama embeds a request in one forward pass, so keep the working set bounded.
_MAX_BATCH = 32
_TIMEOUT_SECONDS = 30
# A finite lease still expires after a crash; renewal stays well inside it.
_KEEP_ALIVE = "5m"
_REFRESH_SECONDS = 60
_LOG = logging.getLogger(__name__)


def embed(inputs: list[str]) -> list[tuple[float, ...]]:
    """Return one vector per input, in order, renewing the model's residency.

    Requests are split into batches internally, so callers pass whatever they
    have. Embedding nothing still makes one request: that is how Ollama loads
    or refreshes a model without embedding text, and is what keep-alive uses.

    Raises ``OSError`` when Ollama is unreachable, and ``ValueError`` when it
    answers with anything other than one finite, equally sized vector per input.
    """
    batches = [inputs[offset:offset + _MAX_BATCH] for offset in range(0, len(inputs), _MAX_BATCH)]
    vectors: list[tuple[float, ...]] = []
    for batch in batches or [[]]:
        vectors.extend(_embed_batch(batch))
    return vectors


def _embed_batch(batch: list[str]) -> list[tuple[float, ...]]:
    request = urllib.request.Request(
        _EMBED_URL,
        data=json.dumps({"model": _EMBED_MODEL, "input": batch, "keep_alive": _KEEP_ALIVE}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
        body = json.load(response)
    if not batch:
        return []
    try:
        vectors = np.asarray(body.get("embeddings"), dtype=np.float32)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid embedding response") from exc
    if (
        vectors.ndim != 2
        or len(vectors) != len(batch)
        or not vectors.shape[1]
        or not np.isfinite(vectors).all()
    ):
        raise ValueError("Invalid embedding response")
    return [tuple(vector) for vector in vectors]


def _refresh_model(stop: Event) -> None:
    failed = False
    while not stop.is_set():
        try:
            # Embedding no text loads or refreshes residency on its own.
            embed([])
            failed = False
        except (OSError, ValueError) as exc:
            if not failed:
                _LOG.warning("Embedding model keep-alive unavailable: %s", type(exc).__name__)
            failed = True
        if stop.wait(_REFRESH_SECONDS):
            return


@contextmanager
def keep_embedding_model_alive():
    """Preload asynchronously; stop renewals without blocking shutdown on HTTP.

    A finite lease also expires after crashes. Do not unload explicitly: another
    app or backend process may be using this same local Ollama model.
    """
    stop = Event()
    worker = Thread(target=_refresh_model, args=(stop,), name="ollama-keep-alive", daemon=True)
    try:
        worker.start()
    except RuntimeError as exc:
        _LOG.warning("Could not start embedding model keep-alive: %s", type(exc).__name__)
    try:
        yield worker
    finally:
        stop.set()
