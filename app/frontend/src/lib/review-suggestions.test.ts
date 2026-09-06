import { afterEach, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { createReviewSuggestions } from './review-suggestions';

const ready = (account: string) => ({ status: 'ready', suggestions: [{ account, probability: 0.9 }] });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it('prepares the next payee before navigation and displays it without a loading flash', async () => {
  const fetcher = vi.fn(async (url: string) => new Response(JSON.stringify(
    ready(url.includes('Market') ? 'Expenses:Food' : 'Expenses:Rent')
  )));
  vi.stubGlobal('fetch', fetcher);
  const suggestions = createReviewSuggestions();
  suggestions.focus('Market', ['Rent']);
  await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
  await vi.waitFor(() => expect(get(suggestions).accounts).toEqual(['Expenses:Food']));
  await new Promise((resolve) => setTimeout(resolve, 0));
  suggestions.focus('Rent', ['Market']);
  expect(get(suggestions)).toEqual({ accounts: ['Expenses:Rent'], message: '' });
  expect(fetcher).toHaveBeenCalledTimes(2);
  suggestions.dispose();
});

it('retries an unavailable suggestion after a cooldown instead of caching failure forever', async () => {
  let now = 0;
  vi.spyOn(Date, 'now').mockImplementation(() => now);
  const fetcher = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ status: 'unavailable', suggestions: [] })))
    .mockResolvedValueOnce(new Response(JSON.stringify(ready('Expenses:Food'))));
  vi.stubGlobal('fetch', fetcher);
  const suggestions = createReviewSuggestions();
  suggestions.focus('Market');
  await vi.waitFor(() => expect(get(suggestions).message).toContain('unavailable'));
  now = 31000;
  suggestions.focus('Market');
  await vi.waitFor(() => expect(get(suggestions).accounts).toEqual(['Expenses:Food']));
  suggestions.dispose();
  vi.restoreAllMocks();
});

it('keeps in-flight work on navigation and never displays a late response for another payee', async () => {
  const replies = new Map<string, (response: Response) => void>();
  const fetcher = vi.fn((url: string) => new Promise<Response>((resolve) => {
    replies.set(new URL(url, 'http://localhost').searchParams.get('payee')!, resolve);
  }));
  vi.stubGlobal('fetch', fetcher);
  const suggestions = createReviewSuggestions();
  suggestions.focus('Market', ['Rent']);
  suggestions.focus('Rent', ['Market']);
  expect(fetcher).toHaveBeenCalledTimes(2);
  replies.get('Rent')!(new Response(JSON.stringify(ready('Expenses:Rent'))));
  await vi.waitFor(() => expect(get(suggestions).accounts).toEqual(['Expenses:Rent']));
  const displayed: string[][] = [];
  const unsubscribe = suggestions.subscribe((state) => displayed.push(state.accounts));
  replies.get('Market')!(new Response(JSON.stringify(ready('Expenses:Food'))));
  await new Promise((resolve) => setTimeout(resolve, 0));
  expect(displayed).toEqual([['Expenses:Rent']]);
  suggestions.focus('Market');
  expect(get(suggestions).accounts).toEqual(['Expenses:Food']);
  unsubscribe();
  suggestions.dispose();
});

it('bounds background requests and stops work when the review closes', async () => {
  const signals: AbortSignal[] = [];
  const fetcher = vi.fn((_url: string, options: { signal: AbortSignal }) => {
    signals.push(options.signal);
    return new Promise<Response>((_resolve, reject) => options.signal.addEventListener('abort', () => reject(new Error('aborted'))));
  });
  vi.stubGlobal('fetch', fetcher);
  const suggestions = createReviewSuggestions();
  suggestions.focus('Market', ['Market', 'Rent', 'Bus', 'Salary', 'Coffee', 'Gas']);
  expect(fetcher).toHaveBeenCalledTimes(2);
  suggestions.dispose();
  expect(signals.every((signal) => signal.aborted)).toBe(true);
  await new Promise((resolve) => setTimeout(resolve, 0));
  expect(fetcher).toHaveBeenCalledTimes(2);
});
