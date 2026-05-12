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
		// Ctrl+K (or Meta+K on Mac) always toggles the palette, even from inputs.
		const paletteKey =
			event.key.toLowerCase() === 'k' && (event.ctrlKey || event.metaKey) && !event.shiftKey && !event.altKey;

		if (paletteKey) {
			event.preventDefault();
			commandPaletteOpen.update((v) => !v);
			return;
		}

		// Skip shortcuts when focus is on an editable element.
		if (isEditableTarget(event.target)) return;

		for (const cmd of $commandRegistry.values()) {
			if (!cmd.shortcut) continue;
			const parsed = parseShortcut(cmd.shortcut);
			if (matchesShortcut(event, parsed)) {
				event.preventDefault();
				cmd.action();
				return;
			}
		}
	}
</script>

<svelte:window on:keydown={handleKeydown} />
