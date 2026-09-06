"""Exercise suggestions with real journals and a fake embedding provider."""
import pytest
from test_category_suggestion_service import _make_config

from services import classifier_service as classifier
from services.classifier_service import suggest_review_categories


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
    # One entry per call to ollama_service.embed, holding that call's inputs.
    requests = []
    def embed(inputs):
        requests.append(list(inputs))
        vectors = []
        for text in inputs:
            assert text.startswith('classification: description: ')
            index = next((i for i, name in enumerate(names) if name in text), 0)
            vectors.append(tuple(float(i == index) for i in range(4)))
        return vectors
    monkeypatch.setattr(classifier.ollama_service, 'embed', embed)
    return config, names, requests, journal


def test_cold_suggestion_batches_history_without_changing_ranking(history):
    config, names, requests, _ = history
    result = suggest_review_categories(names[0], config)
    assert result['status'] == 'ready'
    assert result['suggestions'][0]['account'] == 'Expenses:Food'
    assert len(result['suggestions']) == 3
    # Asking the provider once per historical payee is the cold-start regression.
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
    respond = classifier.ollama_service.embed
    def offline(inputs):
        raise OSError('offline')
    monkeypatch.setattr(classifier.ollama_service, 'embed', offline)
    assert suggest_review_categories(names[0], config)['status'] == 'unavailable'
    monkeypatch.setattr(classifier.ollama_service, 'embed', respond)
    assert suggest_review_categories(names[0], other)['status'] == 'ready'


def test_warmup_prepares_model_and_deduplicated_unresolved_payees(history, monkeypatch):
    config, names, requests, journal = history
    journal.write_text(journal.read_text() + '\n' + '\n'.join(
        f'2026-02-01 {payee}\n    Expenses:Unknown  USD 10\n    Assets:Bank\n'
        for payee in ['New shop', 'New shop', 'Other shop']))
    classifier.warm_review_classifier(config)
    embedded = [text for call in requests for text in call]
    assert embedded.count('classification: description: New shop') == 1
    assert embedded.count('classification: description: Other shop') == 1
    fits = classifier._fit.cache_info().misses
    requests.clear()
    for payee in ['New shop', 'Other shop', names[0]]:
        assert classifier.suggest_review_categories(payee, config)['status'] == 'ready'
    assert requests == []
    assert classifier._fit.cache_info().misses == fits


def test_warmed_model_invalidates_on_history_change_and_undo(history):
    config, names, requests, journal = history
    original = journal.read_text()
    classifier.warm_review_classifier(config)
    requests.clear()
    journal.write_text(original.replace('Expenses:Food', 'Expenses:Groceries'))
    assert classifier.suggest_review_categories(names[0], config)['suggestions'][0]['account'] == 'Expenses:Groceries'
    journal.write_text(original)
    assert classifier.suggest_review_categories(names[0], config)['suggestions'][0]['account'] == 'Expenses:Food'
    assert requests == []


def test_warmup_failure_allows_retry_after_cooldown(history, monkeypatch):
    config, names, requests, _ = history
    respond = classifier.ollama_service.embed
    now = [100.0]
    monkeypatch.setattr(classifier, 'monotonic', lambda: now[0])
    def offline(inputs):
        raise OSError('offline')
    monkeypatch.setattr(classifier.ollama_service, 'embed', offline)
    classifier.warm_review_classifier(config)
    assert classifier.suggest_review_categories(names[0], config)['status'] == 'unavailable'
    monkeypatch.setattr(classifier.ollama_service, 'embed', respond)
    now[0] += 31
    classifier.warm_review_classifier(config)
    requests.clear()
    assert classifier.suggest_review_categories(names[0], config)['status'] == 'ready'
    assert requests == []


def test_warmup_yields_between_batches_rather_than_holding_the_lock(history, monkeypatch):
    """Interactive requests must not queue behind a whole warmup pass."""
    config, _, _, journal = history
    journal.write_text(journal.read_text() + '\n' + '\n'.join(
        f'2026-02-{day:02d} Unresolved {day}\n    Expenses:Unknown  USD 10\n    Assets:Bank\n'
        for day in range(1, 40)))
    monkeypatch.setattr(classifier, '_WARMUP_BATCH', 4)
    batches = []
    embed = classifier.ollama_service.embed
    def counting_embed(inputs):
        batches.append(len(inputs))
        # The lock is free between batches, which is what lets review overtake.
        assert not classifier._LOCK.foreground_waiting()
        return embed(inputs)
    monkeypatch.setattr(classifier.ollama_service, 'embed', counting_embed)
    classifier.warm_review_classifier(config)
    assert len(batches) > 1 and max(batches) <= 4
