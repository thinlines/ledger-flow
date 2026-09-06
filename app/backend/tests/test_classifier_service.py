"""Exercise suggestions with real journals and a fake Ollama HTTP transport."""
import io
import json

import pytest

from services.classifier_service import suggest_review_categories
from test_category_suggestion_service import _make_config


@pytest.fixture
def history(tmp_path, monkeypatch):
    config = _make_config(tmp_path)
    prefix = tmp_path.name
    names = [f'{prefix} market', f'{prefix} rent', f'{prefix} bus', f'{prefix} salary']
    categories = ['Expenses:Food', 'Expenses:Rent', 'Expenses:Travel', 'Income:Salary']
    journal = config.journal_dir / '2026.journal'
    journal.write_text('\n'.join(
        f'2026-01-01 {name}\n    {category}  USD 10\n    Assets:Bank\n'
        for name, category in zip(names, categories)))
    requests = []
    def respond(request, timeout):
        payload = json.loads(request.data)
        requests.append(payload)
        vectors = []
        for text in payload['input']:
            assert text.startswith('classification: description: ')
            index = next((i for i, name in enumerate(names) if name in text), 0)
            vectors.append([float(i == index) for i in range(4)])
        return io.StringIO(json.dumps({'embeddings': vectors}))
    monkeypatch.setattr('urllib.request.urlopen', respond)
    return config, names, requests, journal


def test_cold_suggestion_batches_history_without_changing_ranking(history):
    config, names, requests, _ = history
    result = suggest_review_categories(names[0], config)
    assert result['status'] == 'ready'
    assert result['suggestions'][0]['account'] == 'Expenses:Food'
    assert len(result['suggestions']) == 3
    # One HTTP round trip per historical payee is the cold-start regression.
    assert len(requests) == 1


def test_history_correction_refits_without_reembedding_unchanged_descriptions(history):
    config, names, requests, journal = history
    assert suggest_review_categories(names[0], config)['suggestions'][0]['account'] == 'Expenses:Food'
    requests.clear()
    journal.write_text(journal.read_text().replace('Expenses:Food', 'Expenses:Groceries'))
    assert suggest_review_categories(names[0], config)['suggestions'][0]['account'] == 'Expenses:Groceries'
    assert requests == []


def test_partial_split_and_transfer_history_cannot_supply_labels(history):
    config, names, _, journal = history
    journal.write_text(
        f'2026-01-01 {names[0]}\n    Expenses:Food  USD 10\n    Assets:Bank\n\n'
        f'2026-01-02 {names[1]}\n    Expenses:Rent  USD 10\n    Expenses:Unknown\n\n'
        f'2026-01-03 {names[2]}\n    Expenses:Travel  USD 5\n    Expenses:Food  USD 5\n    Assets:Bank\n\n'
        f'2026-01-04 {names[3]}\n    Assets:Bank  USD 10\n    Assets:Savings\n')
    assert suggest_review_categories(names[0], config) == {'status': 'insufficient_history', 'suggestions': []}


def test_ollama_failure_does_not_poison_another_workspace(history, tmp_path, monkeypatch):
    config, names, _, journal = history
    other = _make_config(tmp_path / 'other')
    (other.journal_dir / '2026.journal').write_text(journal.read_text())
    from urllib import request
    respond = request.urlopen
    def offline(*args, **kwargs):
        raise OSError('offline')
    monkeypatch.setattr(request, 'urlopen', offline)
    assert suggest_review_categories(names[0], config)['status'] == 'unavailable'
    monkeypatch.setattr(request, 'urlopen', respond)
    assert suggest_review_categories(names[0], other)['status'] == 'ready'
