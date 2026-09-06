"""The local embedding provider: request protocol, validation, and residency."""
import asyncio
from contextlib import contextmanager
import io
import json
from threading import Event
from types import SimpleNamespace

import pytest

from services import ollama_service as ollama


@pytest.fixture
def transport(monkeypatch):
    """Capture request payloads and answer with a scripted response body."""
    calls = []
    responder = SimpleNamespace(reply=lambda inputs: {'embeddings': [[1., 0.] for _ in inputs]})

    def urlopen(request, timeout):
        assert request.full_url == ollama._EMBED_URL
        assert request.headers['Content-type'] == 'application/json'
        assert timeout == ollama._TIMEOUT_SECONDS
        payload = json.loads(request.data)
        calls.append(payload)
        return io.StringIO(json.dumps(responder.reply(payload['input'])))

    monkeypatch.setattr(ollama.urllib.request, 'urlopen', urlopen)
    return SimpleNamespace(calls=calls, responder=responder)


def test_embeds_every_input_in_order_across_batches(transport):
    transport.responder.reply = lambda inputs: {
        'embeddings': [[float(text.removeprefix('text')), 0.] for text in inputs]
    }
    inputs = [f'text{i}' for i in range(70)]

    vectors = ollama.embed(inputs)

    assert vectors == [(float(i), 0.) for i in range(70)]
    # Batching is the provider's concern; callers pass whatever they have.
    assert [len(call['input']) for call in transport.calls] == [32, 32, 6]
    assert [text for call in transport.calls for text in call['input']] == inputs


def test_every_request_renews_the_residency_lease(transport):
    ollama.embed([f'text{i}' for i in range(40)])
    assert [call['keep_alive'] for call in transport.calls] == [ollama._KEEP_ALIVE] * 2
    assert {call['model'] for call in transport.calls} == {'nomic-embed-text'}


def test_embedding_nothing_still_makes_one_residency_request(transport):
    assert ollama.embed([]) == []
    assert transport.calls == [{'model': 'nomic-embed-text', 'input': [], 'keep_alive': '5m'}]


@pytest.mark.parametrize('reply', [
    {},
    {'embeddings': None},
    # One vector per input, all the same width, all finite.
    {'embeddings': [[1., 0.]]},
    {'embeddings': [[1., 0.], [1.]]},
    {'embeddings': [[], []]},
    {'embeddings': [[1., float('nan')], [0., 1.]]},
    {'embeddings': [1., 0.]},
])
def test_malformed_responses_are_rejected_rather_than_embedded(transport, reply):
    transport.responder.reply = lambda inputs: reply
    with pytest.raises(ValueError):
        ollama.embed(['first', 'second'])


def test_unreachable_ollama_surfaces_as_oserror(monkeypatch):
    def offline(request, timeout):
        raise OSError('offline')
    monkeypatch.setattr(ollama.urllib.request, 'urlopen', offline)
    with pytest.raises(OSError):
        ollama.embed(['first'])


def test_preloads_without_blocking_and_stops_after_inflight_request(monkeypatch):
    started, release = Event(), Event()
    requests = []
    def respond(request, timeout):
        requests.append(json.loads(request.data))
        started.set()
        assert release.wait(5)
        return io.BytesIO(b'{"embeddings": []}')
    monkeypatch.setattr(ollama.urllib.request, 'urlopen', respond)
    try:
        with ollama.keep_embedding_model_alive() as worker:
            assert started.wait(2)
        # Exiting does not wait on the blocked network request.
        assert worker.is_alive()
    finally:
        release.set()
        worker.join(2)
    assert not worker.is_alive()
    assert requests == [{'model': 'nomic-embed-text', 'input': [], 'keep_alive': '5m'}]


def test_refreshes_every_minute_and_recovers_after_ollama_outage(monkeypatch, caplog):
    waits, calls = [], []
    class Clock:
        def is_set(self):
            return False
        def wait(self, seconds):
            waits.append(seconds)
            return len(waits) == 4
    def respond(request, timeout):
        calls.append(json.loads(request.data))
        if len(calls) < 3:
            raise OSError('offline')
        return io.BytesIO(b'{"embeddings": []}')
    monkeypatch.setattr(ollama.urllib.request, 'urlopen', respond)
    ollama._refresh_model(Clock())
    assert waits == [60] * 4
    assert len(calls) == 4
    assert all(call['keep_alive'] == '5m' and call['input'] == [] for call in calls)
    assert caplog.text.count('Embedding model keep-alive unavailable') == 1


@pytest.mark.parametrize("has_workspace", [False, True])
def test_app_lifespan_owns_model_residency(monkeypatch, tmp_path, has_workspace):
    import main
    from test_category_suggestion_service import _make_config
    config = _make_config(tmp_path) if has_workspace else None
    events = []
    warmed = []
    @contextmanager
    def residency():
        events.append('start')
        try:
            yield
        finally:
            events.append('stop')
    monkeypatch.setattr(main, 'keep_embedding_model_alive', residency)
    monkeypatch.setattr(main, 'workspace_manager', SimpleNamespace(load_active_config=lambda: config))
    monkeypatch.setattr(main, 'hours_since_last_snapshot', lambda root: 0)
    monkeypatch.setattr(main, 'snapshot_commit', lambda *args, **kwargs: None)
    monkeypatch.setattr(main, 'schedule_review_warmup', warmed.append)
    async def run():
        async with main.lifespan(main.app):
            assert events == ['start']
            assert warmed == ([config] if config is not None else [])
        assert events == ['start', 'stop']
    asyncio.run(run())
