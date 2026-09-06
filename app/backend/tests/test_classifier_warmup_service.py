"""Background preparation stays bounded and never blocks import completion."""
from threading import Event

from services.classifier_warmup_service import _WarmupQueue
from test_category_suggestion_service import _make_config


def test_schedule_returns_while_preparation_runs_and_coalesces_imports(tmp_path):
    config = _make_config(tmp_path / 'first')
    other = _make_config(tmp_path / 'second')
    started, release = Event(), Event()
    calls = []

    def prepare(current):
        calls.append(current.root_dir)
        if len(calls) == 1:
            started.set()
            assert release.wait(5)

    queue = _WarmupQueue(prepare)
    queue.schedule(config)
    worker = queue._worker
    try:
        assert started.wait(2)
        for _ in range(20):
            queue.schedule(config)
        queue.schedule(other)
        assert calls == [config.root_dir]
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert calls == [config.root_dir, config.root_dir, other.root_dir]


def test_worker_recovers_from_failure_and_limits_pending_workspaces(tmp_path):
    configs = [_make_config(tmp_path / str(i)) for i in range(7)]
    started, release = Event(), Event()
    calls = []

    def prepare(config):
        calls.append(config.root_dir)
        if len(calls) == 1:
            started.set()
            assert release.wait(5)
            raise OSError('workspace unavailable')

    queue = _WarmupQueue(prepare)
    queue.schedule(configs[0])
    worker = queue._worker
    try:
        assert started.wait(2)
        for config in configs[1:]:
            queue.schedule(config)
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert calls == [configs[0].root_dir, *(config.root_dir for config in configs[-4:])]
    # A completed worker can be started again.
    queue.schedule(configs[0])
    worker = queue._worker
    if worker:
        worker.join(5)
    assert calls[-1] == configs[0].root_dir


def test_scheduling_failure_is_best_effort(tmp_path, monkeypatch):
    from services import classifier_warmup_service as service
    config = _make_config(tmp_path)
    def fail(config):
        raise RuntimeError('cannot start thread')
    monkeypatch.setattr(service._QUEUE, 'schedule', fail)
    service.schedule_review_warmup(config)
