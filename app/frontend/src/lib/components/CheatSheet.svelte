<script lang="ts">
	import { onMount } from 'svelte';
	import { Dialog as DialogPrimitive } from 'bits-ui';
	import { cheatSheetGroups } from '$lib/keyboard/keymap';
	import { availableVerbs, cheatSheetOpen, dismissWhileOpen } from '$lib/keyboard/runtime';

	const groups = cheatSheetGroups();

	// While open, the sheet is a layer in the dismiss stack, so Escape closes
	// it and nothing underneath it. Esc handling stays with the keymap — the
	// dialog's own escape behavior is turned off below.
	onMount(() => dismissWhileOpen(cheatSheetOpen));

	function chordKeys(chord: string): string[] {
		return chord.includes('+') ? [chord] : chord.split(' ');
	}
</script>

<DialogPrimitive.Root bind:open={$cheatSheetOpen}>
	<DialogPrimitive.Portal>
		<DialogPrimitive.Overlay class="fixed inset-0 z-40 bg-ink/20" />

		<DialogPrimitive.Content
			class="fixed top-1/2 left-1/2 z-50 w-[min(26rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-lg border border-hairline bg-panel p-5 shadow-lg"
			aria-label="Keyboard shortcuts"
			escapeKeydownBehavior="ignore"
		>
			<div class="flex items-baseline justify-between gap-3">
				<DialogPrimitive.Title class="m-0 text-sm font-semibold text-ink">
					Keyboard shortcuts
				</DialogPrimitive.Title>
				<span class="text-xs text-ink-mute">press <span class="kbd">?</span> to close</span>
			</div>

			<div class="mt-4 grid gap-4">
				{#each groups as group (group.group)}
					<section>
						<h3 class="m-0 mb-1.5 text-[0.6875rem] font-medium tracking-wide text-ink-mute uppercase">
							{group.group}
						</h3>
						<ul class="m-0 grid list-none gap-0.5 p-0">
							{#each group.entries as entry (entry.chord)}
								{@const active = $availableVerbs.has(entry.verb)}
								<!-- Keys with no target here are shown inert, never repurposed (ADR-0003). -->
								<li
									class="flex items-center justify-between gap-4 py-1 {active ? '' : 'opacity-40'}"
								>
									<span class="text-sm text-ink">{entry.label}</span>
									<span class="flex shrink-0 gap-1">
										{#each chordKeys(entry.chord) as key, i (i)}
											<span class="kbd">{key}</span>
										{/each}
									</span>
								</li>
							{/each}
						</ul>
					</section>
				{/each}
			</div>
		</DialogPrimitive.Content>
	</DialogPrimitive.Portal>
</DialogPrimitive.Root>
