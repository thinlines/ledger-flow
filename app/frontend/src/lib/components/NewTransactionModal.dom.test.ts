// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { tick } from 'svelte';
import NewTransactionModal from './NewTransactionModal.svelte';
import { dispatchVerb, resetKeyboardRuntime } from '$lib/keyboard/runtime';
import { showUndoToast } from '$lib/undo-toast';

vi.mock('$lib/undo-toast', () => ({ showUndoToast: vi.fn() }));

function json(body: unknown, init?: ResponseInit) {
	return new Response(JSON.stringify(body), {
		headers: { 'Content-Type': 'application/json' },
		...init
	});
}

function stubApi() {
	return vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
		const path = String(input);
		if (path === '/api/tracked-accounts') {
			return json({ trackedAccounts: [
				{ id: 'checking', displayName: 'Checking', ledgerAccount: 'Assets:Checking', kind: 'asset', institutionId: null, importConfigured: true },
				{ id: 'visa', displayName: 'Visa', ledgerAccount: 'Liabilities:Visa', kind: 'liability', institutionId: null, importConfigured: true }
			] });
		}
		if (path === '/api/accounts') {
			return json({ accounts: ['Expenses:Dining', 'Expenses:Groceries', 'Expenses:Transport'] });
		}
		if (path.startsWith('/api/categories/review-suggestions')) {
			return json({ status: 'ready', suggestions: [
				{ account: 'Expenses:Groceries', probability: 0.62 },
				{ account: 'Expenses:Dining', probability: 0.28 },
				{ account: 'Expenses:Transport', probability: 0.1 }
			] });
		}
		if (path === '/api/transactions/create' && init?.method === 'POST') {
			return json({ created: true, txnId: 'txn_manual_1', eventId: 'event-1' });
		}
		throw new Error(`Unexpected request: ${path}`);
	});
}

afterEach(() => {
	cleanup();
	resetKeyboardRuntime();
	vi.clearAllMocks();
	vi.unstubAllGlobals();
});

describe('new transaction modal', () => {
	it('opens from the global verb and keeps prediction shortcuts separate from combobox filtering', async () => {
		vi.stubGlobal('fetch', stubApi());
		render(NewTransactionModal);

		expect(dispatchVerb('transaction.new')).toBe(true);
		const dialog = await screen.findByRole('dialog', { name: 'New transaction' });
		const date = within(dialog).getByLabelText('Transaction date');
		await waitFor(() => expect(document.activeElement).toBe(date));

		await fireEvent.input(within(dialog).getByLabelText('Payee'), { target: { value: 'Cafe' } });
		await waitFor(() => expect(within(dialog).getAllByText('Expenses:Groceries')).not.toHaveLength(0));

		await fireEvent.keyDown(window, { key: '2', code: 'Digit2', altKey: true });
		const category = within(dialog).getByRole('combobox', { name: 'Category' });
		expect(category.getAttribute('placeholder')).toBe('Expenses:Dining');

		await fireEvent.focus(category);
		await fireEvent.input(category, { target: { value: 'gro' } });
		const listbox = within(dialog).getByRole('listbox');
		expect(within(listbox).getByText('Expenses:Groceries')).not.toBeNull();
		expect(within(listbox).queryByText('Expenses:Dining')).toBeNull();

		await fireEvent.keyDown(category, { key: 'Tab' });
		expect(category.getAttribute('placeholder')).toBe('Expenses:Groceries');

		await fireEvent.focus(category);
		await fireEvent.keyDown(category, { key: 'Tab' });
		expect(category.getAttribute('placeholder')).toBe('Expenses:Groceries');
	});

	it('posts the selected transaction and exposes its undo operation', async () => {
		const fetchMock = stubApi();
		vi.stubGlobal('fetch', fetchMock);
		render(NewTransactionModal);
		dispatchVerb('transaction.new');
		const dialog = await screen.findByRole('dialog', { name: 'New transaction' });

		await fireEvent.input(within(dialog).getByLabelText('Payee'), { target: { value: 'Corner Cafe' } });
		await waitFor(() => expect(within(dialog).getAllByText('Expenses:Groceries')).not.toHaveLength(0));
		await fireEvent.input(within(dialog).getByLabelText('Amount'), { target: { value: '12.50' } });
		await fireEvent.change(within(dialog).getByLabelText('From'), { target: { value: 'Liabilities:Visa' } });
		await fireEvent.input(within(dialog).getByLabelText('Memo'), { target: { value: 'Lunch' } });
		await fireEvent.click(within(dialog).getByRole('button', { name: /Capture/ }));
		await tick();

		const createCall = fetchMock.mock.calls.find(([input]) => String(input) === '/api/transactions/create');
		expect(createCall).toBeDefined();
		expect(JSON.parse(String(createCall?.[1]?.body))).toMatchObject({
			payee: 'Corner Cafe',
			amount: '12.50',
			sourceAccount: 'Liabilities:Visa',
			destinationAccount: 'Expenses:Groceries',
			notes: 'Lunch'
		});
		expect(showUndoToast).toHaveBeenCalledWith('event-1', 'Created Corner Cafe for $12.50');
		expect(screen.queryByRole('dialog', { name: 'New transaction' })).toBeNull();
	});

	it('supports submit, submit-and-new, and memo focus shortcuts', async () => {
		const fetchMock = stubApi();
		vi.stubGlobal('fetch', fetchMock);
		render(NewTransactionModal);
		dispatchVerb('transaction.new');
		const dialog = await screen.findByRole('dialog', { name: 'New transaction' });
		const payee = within(dialog).getByLabelText('Payee');
		const amount = within(dialog).getByLabelText('Amount');

		await fireEvent.input(payee, { target: { value: 'First Cafe' } });
		await fireEvent.input(amount, { target: { value: '4.00' } });
		await fireEvent.keyDown(window, { key: ';', code: 'Semicolon', altKey: true });
		expect(document.activeElement).toBe(within(dialog).getByLabelText('Memo'));
		await fireEvent.keyDown(window, { key: 'Enter', code: 'Enter', shiftKey: true });
		await waitFor(() => expect(fetchMock.mock.calls.filter(([input]) => String(input) === '/api/transactions/create')).toHaveLength(1));
		expect(screen.queryByRole('dialog', { name: 'New transaction' })).not.toBeNull();

		await fireEvent.input(payee, { target: { value: 'Second Cafe' } });
		await fireEvent.input(amount, { target: { value: '5.00' } });
		await fireEvent.keyDown(window, { key: 'Enter', code: 'Enter', ctrlKey: true });
		await waitFor(() => expect(fetchMock.mock.calls.filter(([input]) => String(input) === '/api/transactions/create')).toHaveLength(2));
		await waitFor(() => expect(screen.queryByRole('dialog', { name: 'New transaction' })).toBeNull());
	});
});
