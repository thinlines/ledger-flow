import { writable } from 'svelte/store';
import { apiGet } from '$lib/api';

type Result = { status: 'ready' | 'insufficient_history' | 'unavailable'; suggestions: { account: string; probability: number }[] };
type View = { accounts: string[]; message: string };

/** One review session owns its cache. Focus also prepares the next four payees. */
export function createReviewSuggestions() {
  const state = writable<View>({ accounts: [], message: '' });
  const cache = new Map<string, Result>();
  const retryAfter = new Map<string, number>();
  const pending = new Map<string, AbortController>();
  let active: string | null = null;
  let queue: string[] = [];
  let disposed = false;

  function publish() {
    const result = active ? cache.get(active) : undefined;
    state.set({
      accounts: result?.suggestions.map((entry) => entry.account) ?? [],
      message: !active ? '' : !result ? 'Loading suggestions…' : result.status === 'ready' ? '' : result.status === 'insufficient_history'
        ? 'More categorized history is needed for suggestions. Choose a category below.'
        : 'Suggestions are unavailable. Choose a category below.'
    });
  }

  function pump() {
    while (!disposed && pending.size < 2 && queue.length) {
      const payee = queue.shift()!;
      if (cache.has(payee) || pending.has(payee)) continue;
      const controller = new AbortController();
      pending.set(payee, controller);
      void apiGet<Result>(`/api/categories/review-suggestions?payee=${encodeURIComponent(payee)}`, { signal: controller.signal })
        .catch((): Result => ({ status: 'unavailable', suggestions: [] }))
        .then((result) => {
          if (disposed) return;
          cache.set(payee, result);
          if (result.status === 'unavailable') retryAfter.set(payee, Date.now() + 30000);
          if (payee === active) publish();
        })
        .finally(() => { pending.delete(payee); pump(); });
    }
  }

  return {
    subscribe: state.subscribe,
    focus(payee: string | null, upcoming: string[] = []) {
      if (disposed) return;
      active = payee;
      for (const [failedPayee, retryAt] of retryAfter) {
        if (Date.now() >= retryAt) { cache.delete(failedPayee); retryAfter.delete(failedPayee); }
      }
      queue = [...new Set([...(payee ? [payee] : []), ...upcoming])].slice(0, 5);
      publish();
      pump();
    },
    dispose() {
      disposed = true;
      queue = [];
      for (const controller of pending.values()) controller.abort();
      cache.clear();
    }
  };
}
