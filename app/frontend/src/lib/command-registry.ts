import { writable } from 'svelte/store';

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

export type ParsedShortcut = {
	key: string;
	ctrl: boolean;
	meta: boolean;
	shift: boolean;
	alt: boolean;
};

export const commandRegistry = writable<Map<string, Command>>(new Map());
export const commandPaletteOpen = writable<boolean>(false);

export function registerCommand(cmd: Command) {
	commandRegistry.update((map) => {
		const next = new Map(map);
		next.set(cmd.id, cmd);
		return next;
	});
}

export function unregisterCommand(id: string) {
	commandRegistry.update((map) => {
		const next = new Map(map);
		next.delete(id);
		return next;
	});
}

export function registerCommands(cmds: Command[]) {
	commandRegistry.update((map) => {
		const next = new Map(map);
		for (const cmd of cmds) {
			next.set(cmd.id, cmd);
		}
		return next;
	});
}

/**
 * Parse a display shortcut string like "Ctrl+Shift+N" into a structured
 * representation suitable for matching against keyboard events.
 */
export function parseShortcut(display: string): ParsedShortcut {
	const parts = display.split('+');
	const modifiers = parts.slice(0, -1).map((m) => m.toLowerCase());
	const key = parts[parts.length - 1].toLowerCase();

	return {
		key,
		ctrl: modifiers.includes('ctrl'),
		meta: modifiers.includes('meta'),
		shift: modifiers.includes('shift'),
		alt: modifiers.includes('alt')
	};
}

/**
 * Check whether a keyboard event matches a parsed shortcut.
 */
export function matchesShortcut(event: KeyboardEvent, parsed: ParsedShortcut): boolean {
	if (event.key.toLowerCase() !== parsed.key) return false;
	if (event.ctrlKey !== parsed.ctrl) return false;
	if (event.metaKey !== parsed.meta) return false;
	if (event.shiftKey !== parsed.shift) return false;
	if (event.altKey !== parsed.alt) return false;
	return true;
}
