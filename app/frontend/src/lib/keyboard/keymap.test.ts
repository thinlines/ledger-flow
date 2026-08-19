import { describe, expect, it } from 'vitest';
import {
  INITIAL_KEYMAP_STATE,
  KEYMAP,
  cheatSheetGroups,
  chordFor,
  labelFor,
  resolveKey,
  type KeyInput
} from './keymap';

function press(key: string, overrides: Partial<KeyInput> = {}): KeyInput {
  return {
    key,
    ctrl: false,
    meta: false,
    alt: false,
    shift: false,
    editable: false,
    interactive: false,
    ...overrides
  };
}

describe('keymap — single-key verbs', () => {
  it('j moves focus down, k moves focus up', () => {
    expect(resolveKey(press('j'), INITIAL_KEYMAP_STATE).verb).toBe('focus.next');
    expect(resolveKey(press('k'), INITIAL_KEYMAP_STATE).verb).toBe('focus.prev');
  });

  it('Enter opens the focused row, Escape dismisses', () => {
    expect(resolveKey(press('Enter'), INITIAL_KEYMAP_STATE).verb).toBe('row.open');
    expect(resolveKey(press('Escape'), INITIAL_KEYMAP_STATE).verb).toBe('dismiss');
  });

  it('s toggles cleared status on the focused row', () => {
    expect(resolveKey(press('s'), INITIAL_KEYMAP_STATE).verb).toBe('row.toggleStatus');
  });

  it('? toggles the cheat sheet and / focuses search', () => {
    expect(resolveKey(press('?', { shift: true }), INITIAL_KEYMAP_STATE).verb).toBe('help.toggle');
    expect(resolveKey(press('/'), INITIAL_KEYMAP_STATE).verb).toBe('search.focus');
  });

  it('handled keys request preventDefault, unknown keys do not', () => {
    expect(resolveKey(press('j'), INITIAL_KEYMAP_STATE).preventDefault).toBe(true);
    expect(resolveKey(press('/'), INITIAL_KEYMAP_STATE).preventDefault).toBe(true);
    const unknown = resolveKey(press('z'), INITIAL_KEYMAP_STATE);
    expect(unknown.verb).toBeNull();
    expect(unknown.preventDefault).toBe(false);
  });

  it('modifier-held letters are left to the browser', () => {
    expect(resolveKey(press('j', { ctrl: true }), INITIAL_KEYMAP_STATE).verb).toBeNull();
    expect(resolveKey(press('t', { alt: true }), INITIAL_KEYMAP_STATE).verb).toBeNull();
  });
});

describe('keymap — g-prefix navigation', () => {
  it('g arms the prefix without emitting a verb', () => {
    const result = resolveKey(press('g'), INITIAL_KEYMAP_STATE);
    expect(result.verb).toBeNull();
    expect(result.state.prefix).toBe('g');
    expect(result.preventDefault).toBe(true);
  });

  it('g then t navigates to Transactions and clears the prefix', () => {
    const armed = resolveKey(press('g'), INITIAL_KEYMAP_STATE).state;
    const result = resolveKey(press('t'), armed);
    expect(result.verb).toBe('nav.transactions');
    expect(result.state.prefix).toBeNull();
  });

  it('g then an unbound key cancels the sequence silently', () => {
    const armed = resolveKey(press('g'), INITIAL_KEYMAP_STATE).state;
    const result = resolveKey(press('x'), armed);
    expect(result.verb).toBeNull();
    expect(result.state.prefix).toBeNull();
  });
});

describe('keymap — editable-target guards', () => {
  it('letters and sequences are inert while typing', () => {
    expect(resolveKey(press('j', { editable: true }), INITIAL_KEYMAP_STATE).verb).toBeNull();
    expect(resolveKey(press('g', { editable: true }), INITIAL_KEYMAP_STATE).state.prefix).toBeNull();
    expect(resolveKey(press('/', { editable: true }), INITIAL_KEYMAP_STATE).verb).toBeNull();
  });

  it('Enter is left to the form while typing', () => {
    expect(resolveKey(press('Enter', { editable: true }), INITIAL_KEYMAP_STATE).verb).toBeNull();
  });

  it('Escape still dismisses from inside an input', () => {
    expect(resolveKey(press('Escape', { editable: true }), INITIAL_KEYMAP_STATE).verb).toBe('dismiss');
  });

  it('Ctrl+K toggles the palette even from inside an input', () => {
    const result = resolveKey(press('k', { ctrl: true, editable: true }), INITIAL_KEYMAP_STATE);
    expect(result.verb).toBe('palette.toggle');
    expect(result.preventDefault).toBe(true);
  });
});

describe('keymap — interactive-target deferral', () => {
  it('Enter defers to a focused button or link instead of opening the row', () => {
    const result = resolveKey(press('Enter', { interactive: true }), INITIAL_KEYMAP_STATE);
    expect(result.verb).toBeNull();
    expect(result.preventDefault).toBe(false);
  });

  it('letter verbs still fire while an interactive control has focus', () => {
    expect(resolveKey(press('j', { interactive: true }), INITIAL_KEYMAP_STATE).verb).toBe(
      'focus.next'
    );
  });

  it('Escape still dismisses while an interactive control has focus', () => {
    expect(resolveKey(press('Escape', { interactive: true }), INITIAL_KEYMAP_STATE).verb).toBe(
      'dismiss'
    );
  });
});

describe('keymap — display derivation', () => {
  it('chordFor and labelFor read straight from the table', () => {
    expect(chordFor('nav.transactions')).toBe('g t');
    expect(labelFor('nav.transactions')).toBe('Go to Transactions');
    expect(chordFor('help.toggle')).toBe('?');
  });

  it('every verb in the table is resolvable', () => {
    for (const entry of KEYMAP) {
      expect(chordFor(entry.verb)).toBe(entry.chord);
      expect(labelFor(entry.verb)).toBe(entry.label);

      const keys = entry.chord === 'Ctrl+K' ? ['k'] : entry.chord.split(' ');
      let state = INITIAL_KEYMAP_STATE;
      let resolution;
      for (const key of keys) {
        resolution = resolveKey(
          press(key === 'Esc' ? 'Escape' : key, {
            ctrl: entry.chord === 'Ctrl+K',
            meta: false,
            shift: entry.chord === '?'
          }),
          state
        );
        state = resolution.state;
      }
      expect(resolution?.verb).toBe(entry.verb);
    }
  });
});

describe('keymap — one key, one verb (ADR-0003)', () => {
  it('no chord is bound to two different verbs', () => {
    const seen = new Map<string, string>();
    for (const entry of KEYMAP) {
      const existing = seen.get(entry.chord);
      expect(existing, `chord "${entry.chord}" bound to both ${existing} and ${entry.verb}`).toBeUndefined();
      seen.set(entry.chord, entry.verb);
    }
  });

  it('every entry carries the copy the cheat sheet needs', () => {
    for (const entry of KEYMAP) {
      expect(entry.label.length).toBeGreaterThan(0);
      expect(entry.group.length).toBeGreaterThan(0);
    }
  });

  it('cheat sheet groups cover the whole table', () => {
    const total = cheatSheetGroups().reduce((n, g) => n + g.entries.length, 0);
    expect(total).toBe(KEYMAP.length);
  });
});
