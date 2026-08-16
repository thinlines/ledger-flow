<script lang="ts">
	import { INITIAL_KEYMAP_STATE, resolveKey, type KeymapState } from '$lib/keyboard/keymap';
	import { dispatchVerb } from '$lib/keyboard/runtime';

	let state: KeymapState = INITIAL_KEYMAP_STATE;

	function isEditableTarget(el: EventTarget | null): boolean {
		if (!el || !(el instanceof HTMLElement)) return false;
		const tag = el.tagName;
		if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
		if (el.isContentEditable) return true;
		return false;
	}

	function handleKeydown(event: KeyboardEvent) {
		const resolved = resolveKey(
			{
				key: event.key,
				ctrl: event.ctrlKey,
				meta: event.metaKey,
				alt: event.altKey,
				shift: event.shiftKey,
				editable: isEditableTarget(event.target)
			},
			state
		);
		state = resolved.state;
		if (resolved.preventDefault) event.preventDefault();
		if (resolved.verb) dispatchVerb(resolved.verb);
	}
</script>

<svelte:window on:keydown={handleKeydown} />
