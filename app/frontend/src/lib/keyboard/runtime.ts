import { writable, type Readable, type Writable } from 'svelte/store';
import type { KeyVerb } from './keymap';

/**
 * Verb bus connecting the global KeyboardListener to whoever currently has
 * a target for a verb. Handlers stack: the most recently registered handler
 * gets the verb first and returns true when it consumed it (so `dismiss`
 * closes the top-most surface only). A verb with no willing handler simply
 * does nothing — keys are inert, never repurposed (ADR-0003).
 */

export type VerbHandler = () => boolean;

const stacks = new Map<KeyVerb, VerbHandler[]>();

const availableVerbsStore = writable<ReadonlySet<KeyVerb>>(new Set());

/**
 * Verbs that currently have at least one handler — i.e. a target exists
 * somewhere. The cheat sheet greys everything else (ADR-0003: inert keys are
 * shown inert, never repurposed).
 */
export const availableVerbs: Readable<ReadonlySet<KeyVerb>> = availableVerbsStore;

function refreshAvailable() {
  const available = new Set<KeyVerb>();
  for (const [verb, stack] of stacks) {
    if (stack.length > 0) available.add(verb);
  }
  availableVerbsStore.set(available);
}

export function onVerb(verb: KeyVerb, handler: VerbHandler): () => void {
  const stack = stacks.get(verb) ?? [];
  stack.push(handler);
  stacks.set(verb, stack);
  refreshAvailable();
  return () => {
    const current = stacks.get(verb) ?? [];
    const i = current.indexOf(handler);
    if (i !== -1) current.splice(i, 1);
    refreshAvailable();
  };
}

export function dispatchVerb(verb: KeyVerb): boolean {
  const stack = stacks.get(verb) ?? [];
  for (let i = stack.length - 1; i >= 0; i--) {
    if (stack[i]()) return true;
  }
  return false;
}

/** Reset module-global keyboard state between independently mounted runtimes. */
export function resetKeyboardRuntime() {
  stacks.clear();
  refreshAvailable();
  cheatSheetOpen.set(false);
  pendingPrefix.set(null);
}

/**
 * Make an open/closed surface (dialog, palette, sheet) a proper layer in the
 * dismiss stack: while `open` is true it sits on top, and Escape closes it —
 * and only it. Overlays must use this instead of their own built-in Escape
 * handling so a single keypress never dismisses two layers at once.
 */
export function dismissWhileOpen(open: Writable<boolean>): () => void {
  let off: (() => void) | null = null;
  const unsubscribe = open.subscribe((isOpen) => {
    if (isOpen && !off) {
      off = onVerb('dismiss', () => {
        open.set(false);
        return true;
      });
    } else if (!isOpen && off) {
      off();
      off = null;
    }
  });
  return () => {
    unsubscribe();
    off?.();
    off = null;
  };
}

/** The `?` cheat-sheet overlay, rendered by the shell. */
export const cheatSheetOpen = writable(false);

/** Armed chord prefix awaiting its second key; the shell renders a hint chip. */
export const pendingPrefix = writable<'g' | null>(null);
