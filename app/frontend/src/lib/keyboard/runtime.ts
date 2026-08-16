import { writable } from 'svelte/store';
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

export function onVerb(verb: KeyVerb, handler: VerbHandler): () => void {
  const stack = stacks.get(verb) ?? [];
  stack.push(handler);
  stacks.set(verb, stack);
  return () => {
    const current = stacks.get(verb) ?? [];
    const i = current.indexOf(handler);
    if (i !== -1) current.splice(i, 1);
  };
}

export function dispatchVerb(verb: KeyVerb): boolean {
  const stack = stacks.get(verb) ?? [];
  for (let i = stack.length - 1; i >= 0; i--) {
    if (stack[i]()) return true;
  }
  return false;
}

/** The `?` cheat-sheet overlay, rendered by the shell. */
export const cheatSheetOpen = writable(false);
