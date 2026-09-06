"""Bounded, best-effort classifier preparation after successful imports."""
import logging
from collections import OrderedDict
from threading import Lock, Thread

from .classifier_service import warm_review_classifier
from .config_service import AppConfig

_LOG = logging.getLogger(__name__)


class _WarmupQueue:
    def __init__(self, prepare=warm_review_classifier):
        self._prepare = prepare
        self._lock = Lock()
        self._pending: OrderedDict[str, AppConfig] = OrderedDict()
        self._worker: Thread | None = None

    def schedule(self, config: AppConfig) -> None:
        with self._lock:
            workspace = str(config.root_dir.resolve())
            # An import during preparation gets one fresh pass, not one job per
            # request. Different workspaces retain their own config snapshots.
            self._pending[workspace] = config
            self._pending.move_to_end(workspace)
            while len(self._pending) > 4:
                self._pending.popitem(last=False)
            if self._worker is None:
                self._worker = Thread(target=self._run, name="classifier-warmup", daemon=True)
                try:
                    self._worker.start()
                except RuntimeError:
                    self._worker = None
                    self._pending.clear()
                    raise

    def _run(self) -> None:
        while True:
            with self._lock:
                if not self._pending:
                    self._worker = None
                    return
                _, config = self._pending.popitem(last=False)
            try:
                self._prepare(config)
            except Exception as exc:
                # Preparation must never turn a committed import into a failure
                # or leave the queue unable to process subsequent imports.
                _LOG.warning("Category classifier preparation failed: %s", type(exc).__name__)


_QUEUE = _WarmupQueue()


def schedule_review_warmup(config: AppConfig) -> None:
    """Return immediately; failures leave on-demand classification available."""
    try:
        _QUEUE.schedule(config)
    except Exception as exc:
        _LOG.warning("Could not schedule classifier preparation: %s", type(exc).__name__)
