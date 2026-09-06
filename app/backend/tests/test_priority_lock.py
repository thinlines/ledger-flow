"""Foreground work overtakes queued background work between critical sections."""
from threading import Event, Thread
from time import monotonic

from services.priority_lock import PriorityLock


def _await_foreground_waiter(lock: PriorityLock) -> None:
    deadline = monotonic() + 2
    while monotonic() < deadline:
        if lock.foreground_waiting():
            return
        Event().wait(.001)
    raise AssertionError('foreground request did not reach the lock')


def test_foreground_request_takes_priority_over_next_background_batch():
    lock = PriorityLock()
    order = []
    background_started = Event()

    def background():
        background_started.set()
        with lock.access(background=True):
            order.append('background')

    def foreground():
        with lock.access():
            order.append('foreground')

    with lock.access(background=True):
        bg = Thread(target=background, daemon=True)
        fg = Thread(target=foreground, daemon=True)
        bg.start()
        assert background_started.wait(2)
        fg.start()
        _await_foreground_waiter(lock)
    fg.join(2)
    bg.join(2)
    assert not fg.is_alive() and not bg.is_alive()
    assert order == ['foreground', 'background']


def test_foreground_requests_do_not_starve_each_other():
    lock = PriorityLock()
    order = []
    with lock.access():
        threads = [Thread(target=lambda n=n: _record(lock, order, n), daemon=True) for n in range(3)]
        for thread in threads:
            thread.start()
        _await_foreground_waiter(lock)
    for thread in threads:
        thread.join(2)
    assert sorted(order) == [0, 1, 2]


def _record(lock: PriorityLock, order: list, value: int) -> None:
    with lock.access():
        order.append(value)


def test_access_releases_the_lock_when_the_critical_section_raises():
    lock = PriorityLock()
    try:
        with lock.access():
            raise ValueError('boom')
    except ValueError:
        pass
    # A failed critical section must not leave the lock held.
    with lock.access(background=True):
        pass
