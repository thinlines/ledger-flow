import { describe, expect, it } from 'vitest';
import { get, writable } from 'svelte/store';
import { availableVerbs, dismissWhileOpen, dispatchVerb, onVerb } from './runtime';

describe('verb bus', () => {
  it('delivers to the most recently registered handler first', () => {
    const order: string[] = [];
    const offA = onVerb('dismiss', () => {
      order.push('a');
      return true;
    });
    const offB = onVerb('dismiss', () => {
      order.push('b');
      return true;
    });
    expect(dispatchVerb('dismiss')).toBe(true);
    expect(order).toEqual(['b']);
    offA();
    offB();
  });

  it('falls through handlers that decline the verb', () => {
    const order: string[] = [];
    const offA = onVerb('dismiss', () => {
      order.push('a');
      return true;
    });
    const offB = onVerb('dismiss', () => {
      order.push('b');
      return false;
    });
    expect(dispatchVerb('dismiss')).toBe(true);
    expect(order).toEqual(['b', 'a']);
    offA();
    offB();
  });

  it('reports unconsumed verbs so the listener can leave the default alone', () => {
    expect(dispatchVerb('row.open')).toBe(false);
    const off = onVerb('row.open', () => false);
    expect(dispatchVerb('row.open')).toBe(false);
    off();
  });
});

describe('availableVerbs', () => {
  it('tracks which verbs currently have a handler', () => {
    expect(get(availableVerbs).has('focus.next')).toBe(false);
    const off = onVerb('focus.next', () => true);
    expect(get(availableVerbs).has('focus.next')).toBe(true);
    off();
    expect(get(availableVerbs).has('focus.next')).toBe(false);
  });
});

describe('dismissWhileOpen', () => {
  it('consumes dismiss only while the surface is open, and closes it', () => {
    const open = writable(false);
    const cleanup = dismissWhileOpen(open);
    expect(dispatchVerb('dismiss')).toBe(false);

    open.set(true);
    expect(dispatchVerb('dismiss')).toBe(true);
    expect(get(open)).toBe(false);

    expect(dispatchVerb('dismiss')).toBe(false);
    cleanup();
  });

  it('shields dismiss handlers registered beneath it', () => {
    let pageDismissals = 0;
    const offPage = onVerb('dismiss', () => {
      pageDismissals += 1;
      return true;
    });

    const open = writable(true);
    const cleanup = dismissWhileOpen(open);

    dispatchVerb('dismiss');
    expect(get(open)).toBe(false);
    expect(pageDismissals).toBe(0);

    dispatchVerb('dismiss');
    expect(pageDismissals).toBe(1);

    cleanup();
    offPage();
  });

  it('unregisters its handler on cleanup even while open', () => {
    const open = writable(true);
    const cleanup = dismissWhileOpen(open);
    cleanup();
    expect(dispatchVerb('dismiss')).toBe(false);
    expect(get(open)).toBe(true);
  });
});
