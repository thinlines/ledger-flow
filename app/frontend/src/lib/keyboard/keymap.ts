/**
 * Global keymap table + pure dispatcher (ADR-0003).
 *
 * One key = one verb app-wide. A key's availability is contextual (a verb
 * with no target simply does nothing where it lands), but its meaning never
 * changes. Navigation lives behind the `g` prefix so single letters stay
 * free for verbs. The cheat sheet (`?`) renders straight from this table —
 * there is exactly one source of truth for what keys do.
 */

export type KeyVerb =
  | 'palette.toggle'
  | 'nav.transactions'
  | 'focus.next'
  | 'focus.prev'
  | 'row.open'
  | 'row.toggleStatus'
  | 'dismiss'
  | 'help.toggle'
  | 'search.focus';

export type KeymapEntry = {
  /** Display chord, e.g. "g t" or "Ctrl+K". Unique across the table. */
  chord: string;
  verb: KeyVerb;
  label: string;
  group: 'Navigate' | 'Register' | 'Everywhere';
};

export const KEYMAP: KeymapEntry[] = [
  { chord: 'g t', verb: 'nav.transactions', label: 'Go to Transactions', group: 'Navigate' },
  { chord: 'j', verb: 'focus.next', label: 'Next row', group: 'Register' },
  { chord: 'k', verb: 'focus.prev', label: 'Previous row', group: 'Register' },
  { chord: 'Enter', verb: 'row.open', label: 'Open the focused row', group: 'Register' },
  { chord: 's', verb: 'row.toggleStatus', label: 'Toggle cleared status', group: 'Register' },
  { chord: '/', verb: 'search.focus', label: 'Search transactions', group: 'Register' },
  { chord: 'Esc', verb: 'dismiss', label: 'Close panel or clear focus', group: 'Everywhere' },
  { chord: '?', verb: 'help.toggle', label: 'Keyboard shortcuts', group: 'Everywhere' },
  { chord: 'Ctrl+K', verb: 'palette.toggle', label: 'Command palette', group: 'Everywhere' }
];

export type KeymapState = { prefix: 'g' | null };

export const INITIAL_KEYMAP_STATE: KeymapState = { prefix: null };

export type KeyInput = {
  key: string;
  ctrl: boolean;
  meta: boolean;
  alt: boolean;
  shift: boolean;
  /** True when the event target is a text input / textarea / contenteditable. */
  editable: boolean;
  /**
   * True when the event target is a non-editable interactive control (button,
   * link, summary). Activation keys defer to the control's native behavior.
   */
  interactive: boolean;
};

export type KeyResolution = {
  verb: KeyVerb | null;
  state: KeymapState;
  preventDefault: boolean;
};

const IDLE: KeymapState = { prefix: null };

function verbFor(verb: KeyVerb, preventDefault = true): KeyResolution {
  return { verb, state: IDLE, preventDefault };
}

function inert(): KeyResolution {
  return { verb: null, state: IDLE, preventDefault: false };
}

/** Single-key verbs, only reachable outside editable targets. */
const SINGLE_KEYS: Record<string, KeyVerb> = {
  j: 'focus.next',
  k: 'focus.prev',
  s: 'row.toggleStatus',
  Enter: 'row.open',
  '?': 'help.toggle',
  '/': 'search.focus'
};

/** `g <key>` navigation targets. */
const G_SEQUENCES: Record<string, KeyVerb> = {
  t: 'nav.transactions'
};

export function resolveKey(input: KeyInput, state: KeymapState): KeyResolution {
  const mod = input.ctrl || input.meta;

  // Modifier globals fire everywhere, including from inputs.
  if (mod && !input.alt && !input.shift && input.key.toLowerCase() === 'k') {
    return verbFor('palette.toggle');
  }

  // Escape keeps its verb even while typing — backing out is always safe.
  if (input.key === 'Escape') {
    return verbFor('dismiss', false);
  }

  // Anything else with a modifier held belongs to the browser.
  if (mod || input.alt) return inert();

  // While typing, letters spell words, Enter submits forms.
  if (input.editable) return inert();

  // On a focused button or link, Enter is that control's activation key —
  // never hijack it to open the roving-focused row.
  if (input.interactive && input.key === 'Enter') return inert();

  if (state.prefix === 'g') {
    const verb = G_SEQUENCES[input.key];
    return verb ? verbFor(verb) : inert();
  }

  if (input.key === 'g') {
    return { verb: null, state: { prefix: 'g' }, preventDefault: true };
  }

  const verb = SINGLE_KEYS[input.key];
  return verb ? verbFor(verb) : inert();
}

function entryFor(verb: KeyVerb): KeymapEntry {
  const entry = KEYMAP.find((e) => e.verb === verb);
  if (!entry) throw new Error(`No keymap entry for verb "${verb}"`);
  return entry;
}

/** Display chord for a verb — the palette and inline hints render from here. */
export function chordFor(verb: KeyVerb): string {
  return entryFor(verb).chord;
}

/** Display label for a verb, shared with the cheat sheet and palette. */
export function labelFor(verb: KeyVerb): string {
  return entryFor(verb).label;
}

export type CheatSheetGroup = { group: KeymapEntry['group']; entries: KeymapEntry[] };

export function cheatSheetGroups(): CheatSheetGroup[] {
  const order: KeymapEntry['group'][] = ['Register', 'Navigate', 'Everywhere'];
  return order
    .map((group) => ({ group, entries: KEYMAP.filter((e) => e.group === group) }))
    .filter((g) => g.entries.length > 0);
}
