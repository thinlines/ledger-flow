<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	// Transactions is the app's home while the other surfaces are rebuilt.
	onMount(() => void goto('/transactions', { replaceState: true }));
</script>

<p class="p-6 text-sm text-ink-mute">
	Opening <a href="/transactions" class="text-brand-deep">Transactions</a>…
</p>
