<script lang="ts">
	import {
		commandRegistry,
		commandPaletteOpen,
		parseShortcut,
		matchesShortcut
	} from '$lib/command-registry';

	function isEditableTarget(el: EventTarget | null): boolean {
		if (!el || !(el instanceof HTMLElement)) return false;
		const tag = el.tagName;
		if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
		if (el.isContentEditable) return true;
		return false;
	}

	function handleKeydown(event: KeyboardEvent) {
		const key = event.key.toLowerCase();
		const mod = event.ctrlKey || event.metaKey;

		// Ctrl+K — always toggles the palette, even from inputs.
		if (mod && key === 'k' && !event.shiftKey && !event.altKey) {
			event.preventDefault();
			commandPaletteOpen.update((v) => !v);
			return;
		}

		// Match registered shortcuts. preventDefault early for all mod-key
		// combos to beat the browser's native handling (e.g. Ctrl+N = new window).
		for (const cmd of $commandRegistry.values()) {
			if (!cmd.shortcut) continue;
			const parsed = parseShortcut(cmd.shortcut);
			if (matchesShortcut(event, parsed)) {
				event.preventDefault();
				// Still respect the editable guard for non-palette shortcuts,
				// but only after preventing the browser default.
				if (isEditableTarget(event.target)) return;
				cmd.action();
				return;
			}
		}
	}
</script>

<svelte:window on:keydown={handleKeydown} />
