// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, within } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { tick } from 'svelte';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$app/stores', () => ({
  page: {
    subscribe(run: (value: { url: URL }) => void) {
      run({ url: new URL('http://localhost/transactions?period=this-month') });
      return () => {};
    }
  }
}));

import Layout from '../../routes/+layout.svelte';
import TransactionsPage from '../../routes/transactions/+page.svelte';
import { commandPaletteOpen, commandRegistry } from '$lib/command-registry';
import {
  cheatSheetOpen,
  onVerb,
  pendingPrefix,
  resetKeyboardRuntime
} from './runtime';
import { KEYMAP } from './keymap';

function keydown(target: Window | Document | Node | Element, key: string, options: KeyboardEventInit = {}) {
  return fireEvent.keyDown(target, { key, bubbles: true, cancelable: true, ...options });
}

function shortcutRow(dialog: HTMLElement, label: string): HTMLLIElement {
  const labelElement = within(dialog).getAllByText(label).find((element) => element.closest('li'));
  const row = labelElement?.closest('li');
  expect(row).not.toBeNull();
  return row!;
}

Element.prototype.scrollIntoView = vi.fn();

async function settle() {
  await tick();
  await Promise.resolve();
}

function json(body: unknown) {
  return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } });
}

function stubTransactionsApi() {
  vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
    const path = String(input);
    if (path === '/api/app/state') return json({ initialized: true, workspaceName: 'Test ledger' });
    if (path === '/api/tracked-accounts') {
      return json({ trackedAccounts: [{ id: 'checking', displayName: 'Checking', ledgerAccount: 'Assets:Checking', kind: 'asset', institutionId: null, importConfigured: true }] });
    }
    if (path === '/api/accounts') return json({ accounts: [] });
    return json({
      baseCurrency: 'USD', filters: { accounts: [], categories: [], period: 'this-month', month: null, status: null, search: null },
      rows: [{ id: 'coffee', date: '2026-08-01', payee: 'Coffee', amount: -4.5, runningBalance: 100, account: { id: 'checking', label: 'Checking' }, categories: [], status: 'unmarked', isTransfer: false, isUnknown: false, isManual: false, isOpeningBalance: false, isAssertion: false, legs: [], detailLines: [] }],
      totalCount: 1, summary: null, accountMeta: null
    });
  }));
}

afterEach(() => {
  cleanup();
  resetKeyboardRuntime();
  commandPaletteOpen.set(false);
  commandRegistry.set(new Map());
  vi.unstubAllGlobals();
});

describe('keyboard overlays in the mounted shell', () => {
  it('opens and closes the shortcuts dialog, rendering every keymap entry', async () => {
    render(Layout);

    await keydown(window, '?', { shiftKey: true });
    await settle();

    const dialog = screen.getByRole('dialog', { name: 'Keyboard shortcuts' });
    for (const entry of KEYMAP) {
      const row = shortcutRow(dialog, entry.label);
      expect(Array.from(row.querySelectorAll('.kbd'), (key) => key.textContent)).toEqual(
        entry.chord.includes('+') ? [entry.chord] : entry.chord.split(' ')
      );
    }

    expect(shortcutRow(dialog, 'Next row').classList.contains('opacity-40')).toBe(true);

    await keydown(window, '?', { shiftKey: true });
    await settle();
    expect(screen.queryByRole('dialog', { name: 'Keyboard shortcuts' })).toBeNull();
  });

  it.each([
    ['Control', 'ctrlKey'],
    ['Meta', 'metaKey']
  ])('opens the palette with %s+K from the page and an input', async (_modifier, property) => {
    render(Layout);

    await keydown(window, 'k', { [property]: true });
    await settle();
    expect(screen.getByPlaceholderText('Type a command or search...')).not.toBeNull();

    await keydown(window, 'k', { [property]: true });
    await settle();
    expect(screen.queryByPlaceholderText('Type a command or search...')).toBeNull();

    const input = document.createElement('input');
    document.body.append(input);
    await keydown(input, 'k', { [property]: true });
    await settle();
    expect(screen.getByPlaceholderText('Type a command or search...')).not.toBeNull();
  });

  it('keeps overlays mutually exclusive and Escape reaches the real detail panel second', async () => {
    stubTransactionsApi();
    render(Layout);
    render(TransactionsPage);
    await screen.findByText('Coffee');
    await fireEvent.click(screen.getByRole('button', { name: 'Open Coffee, $4.50' }));
    await settle();
    expect(screen.getByRole('complementary', { name: 'Transaction details' })).not.toBeNull();

    cheatSheetOpen.set(true);
    await settle();
    await keydown(window, 'k', { ctrlKey: true });
    await settle();
    expect(screen.queryByRole('dialog', { name: 'Keyboard shortcuts' })).toBeNull();
    expect(screen.getByPlaceholderText('Type a command or search...')).not.toBeNull();

    await keydown(window, 'Escape');
    await settle();
    expect(screen.queryByPlaceholderText('Type a command or search...')).toBeNull();
    expect(screen.getByRole('complementary', { name: 'Transaction details' })).not.toBeNull();

    await keydown(window, 'Escape');
    await settle();
    expect(screen.queryByRole('complementary', { name: 'Transaction details' })).toBeNull();
  });

  it('classifies editable and interactive targets through the real listener', async () => {
    render(Layout);
    let nextCalls = 0;
    const off = onVerb('focus.next', () => {
      nextCalls += 1;
      return true;
    });
    const editable = [document.createElement('input'), document.createElement('select')];
    const contenteditable = document.createElement('div');
    contenteditable.setAttribute('contenteditable', 'true');
    editable.push(contenteditable as HTMLInputElement);

    for (const target of editable) {
      document.body.append(target);
      await keydown(target, 'j');
    }
    expect(nextCalls).toBe(0);

    for (const target of [
      document.createElement('button'),
      Object.assign(document.createElement('a'), { href: '#' }),
      Object.assign(document.createElement('div'), { role: 'button' })
    ]) {
      document.body.append(target);
      await keydown(target, 'j');
    }
    expect(nextCalls).toBe(3);
    off();
  });

  it('clears an armed prefix after pointer interaction', async () => {
    render(Layout);
    await keydown(window, 'g');
    expect(await new Promise<'g' | null>((resolve) => pendingPrefix.subscribe(resolve)())).toBe('g');

    await fireEvent.pointerDown(window);
    expect(await new Promise<'g' | null>((resolve) => pendingPrefix.subscribe(resolve)())).toBeNull();
  });
});
