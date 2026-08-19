<script lang="ts">
	import { INITIAL_KEYMAP_STATE, resolveKey, type KeymapState } from '$lib/keyboard/keymap';
	import { dispatchVerb, pendingPrefix } from '$lib/keyboard/runtime';

	let state: KeymapState = INITIAL_KEYMAP_STATE;

	function isEditableTarget(el: EventTarget | null): boolean {
		if (!el || !(el instanceof HTMLElement)) return false;
		const tag = el.tagName;
		if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
		if (el.isContentEditable || el.getAttribute('contenteditable') === 'true') return true;
		return false;
	}

	function isInteractiveTarget(el: EventTarget | null): boolean {
		if (!el || !(el instanceof HTMLElement)) return false;
		const tag = el.tagName;
		if (tag === 'BUTTON' || tag === 'SUMMARY') return true;
		if (tag === 'A' && el.hasAttribute('href')) return true;
		const role = el.getAttribute('role');
		return role === 'button' || role === 'link' || role === 'menuitem';
	}

	function setState(next: KeymapState) {
		state = next;
		pendingPrefix.set(next.prefix);
	}

	function handleKeydown(event: KeyboardEvent) {
		const resolved = resolveKey(
			{
				key: event.key,
				ctrl: event.ctrlKey,
				meta: event.metaKey,
				alt: event.altKey,
				shift: event.shiftKey,
				editable: isEditableTarget(event.target),
				interactive: isInteractiveTarget(event.target)
			},
			state
		);
		setState(resolved.state);
		const consumed = resolved.verb ? dispatchVerb(resolved.verb) : false;
		// A consumed verb owns the keypress outright — e.g. Escape that closed a
		// layer must not also trigger the browser's own Escape behavior.
		if (resolved.preventDefault || consumed) event.preventDefault();
	}

	function handlePointerdown() {
		if (state.prefix) setState(INITIAL_KEYMAP_STATE);
	}
</script>

<svelte:window on:keydown={handleKeydown} on:pointerdown={handlePointerdown} />
