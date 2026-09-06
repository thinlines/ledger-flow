"""Mutual exclusion that lets interactive work overtake queued background work."""
from __future__ import annotations

from contextlib import contextmanager
from threading import Condition


class PriorityLock:
    """Serialize access, admitting foreground waiters ahead of background ones.

    ``access()`` is the foreground form and ``access(background=True)`` the
    background one; both block until the lock is free, but a background waiter
    additionally yields to any foreground waiter that has already arrived.

    Priority applies only at acquisition. A critical section already running is
    never interrupted, so background callers that hold the lock for a long time
    must split their work into separate ``access`` blocks to stay yielding.
    Waiters of the same kind are not otherwise ordered.
    """

    def __init__(self) -> None:
        self._condition = Condition()
        self._busy = False
        self._foreground_waiters = 0

    def foreground_waiting(self) -> bool:
        """Whether a foreground caller is currently blocked on acquisition."""
        with self._condition:
            return bool(self._foreground_waiters)

    @contextmanager
    def access(self, *, background: bool = False):
        with self._condition:
            if not background:
                self._foreground_waiters += 1
            try:
                self._condition.wait_for(
                    lambda: not self._busy and (not background or not self._foreground_waiters)
                )
                self._busy = True
            finally:
                if not background:
                    self._foreground_waiters -= 1
        try:
            yield
        finally:
            with self._condition:
                self._busy = False
                self._condition.notify_all()
