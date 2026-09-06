// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import Review from '../routes/review/+page.svelte';
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$app/stores', () => ({ page: { subscribe(run: (value: { url: URL }) => void) { run({ url: new URL('http://localhost/review?journal=test') }); return () => {}; } } }));
const json = (body: unknown) => new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } });
beforeEach(() => {
  let stage = {
    stageId: 'review', selections: {},
    transactions: ['First', 'Second'].map((payee, i) => ({ transactionId: `t${i}`, payee, date: '2026-09-01', amount: '-10' })),
    groups: ['First', 'Second'].map((payeeDisplay, i) => ({ payeeDisplay, txns: [{ txnId: `u${i}`, transactionId: `t${i}`, date: '2026-09-01', amount: '-10' }] }))
  };
  vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
    if (input === '/api/unknowns/scan') return json(stage);
    if (input === '/api/accounts') return json({ accounts: ['Expenses:Food', 'Expenses:Travel', 'Expenses:Books'] });
    if (input === '/api/tracked-accounts') return json({ trackedAccounts: [] });
    if (input.startsWith('/api/categories/review-suggestions')) return json({ status: 'ready', suggestions: [{ account: 'Expenses:Food', probability: .7 }, { account: 'Expenses:Travel', probability: .3 }] });
    if (input === '/api/unknowns/stage-mappings') {
      const { selections } = JSON.parse(String(init?.body));
      stage = { ...stage, selections: Object.fromEntries(selections.map((s: { txnId: string }) => [s.txnId, s])) };
      return json(stage);
    }
    throw new Error(`Unexpected request ${input}`);
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it('shows only the staged suggestion as selected when revisiting a transaction', async () => {
  render(Review);
  await fireEvent.click(await screen.findByRole('button', { name: /Expenses:Travel/ }));
  await waitFor(() => expect(screen.getByRole('heading', { level: 2 }).textContent).toBe('Second'));
  await fireEvent.click(screen.getByRole('button', { name: /First/ }));
  const selected = await screen.findByRole('button', { name: /Expenses:Travel/ });
  expect(selected.getAttribute('aria-pressed')).toBe('true');
  expect(selected.classList.contains('bg-brand-wash')).toBe(true);
  expect(screen.getByRole('button', { name: /Expenses:Food/ }).classList.contains('bg-brand-wash')).toBe(false);
});
it('remembers a manually chosen category after advancing and revisiting', async () => {
  render(Review);
  const input = await screen.findByRole('combobox');
  await fireEvent.input(input, { target: { value: 'Books' } });
  await fireEvent.click(screen.getByRole('option', { name: 'Expenses:Books' }));
  await waitFor(() => expect(screen.getByRole('heading', { level: 2 }).textContent).toBe('Second'));
  await fireEvent.click(screen.getByRole('button', { name: /First/ }));
  expect(await screen.findByText('Staged category: Expenses:Books')).toBeTruthy();
  expect((screen.getByRole('combobox') as HTMLInputElement).value).toBe('Expenses:Books');
});
it('confirms a manual choice when the queue does not advance', async () => {
  render(Review);
  await fireEvent.click(await screen.findByRole('button', { name: /Second/ }));
  await fireEvent.input(screen.getByRole('combobox'), { target: { value: 'Books' } });
  await fireEvent.click(screen.getByRole('option', { name: 'Expenses:Books' }));
  expect(await screen.findByText('Staged category: Expenses:Books')).toBeTruthy();
  expect(screen.getByRole('option', { name: 'Expenses:Books' }).getAttribute('aria-selected')).toBe('true');
});
