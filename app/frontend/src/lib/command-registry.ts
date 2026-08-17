import { writable } from 'svelte/store';

/**
 * Registry backing the Ctrl+K palette. Commands carry actions, keywords and
 * hrefs; anything a command shows about its keyboard shortcut (chord, label)
 * must be derived from the keymap table (`keyboard/keymap.ts`) — that table
 * is the single source of truth for what keys do (ADR-0003).
 */

export type CommandCategory = 'navigation' | 'actions';

export type Command = {
	id: string;
	label: string;
	shortcut?: string;
	category: CommandCategory;
	action: () => void;
	keywords?: string[];
	/** Navigation commands can carry an href for proper link rendering. */
	href?: string;
};

export const commandRegistry = writable<Map<string, Command>>(new Map());
export const commandPaletteOpen = writable<boolean>(false);

export function registerCommands(cmds: Command[]) {
	commandRegistry.update((map) => {
		const next = new Map(map);
		for (const cmd of cmds) {
			next.set(cmd.id, cmd);
		}
		return next;
	});
}
