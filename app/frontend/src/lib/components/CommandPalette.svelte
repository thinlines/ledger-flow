<script lang="ts">
	import { commandRegistry, commandPaletteOpen } from '$lib/command-registry';
	import type { Command as CommandType } from '$lib/command-registry';
	import * as Command from '$lib/components/ui/command/index.js';
	import ArrowRightIcon from '@lucide/svelte/icons/arrow-right';
	import ZapIcon from '@lucide/svelte/icons/zap';

	let search = '';

	$: commands = Array.from($commandRegistry.values());

	$: actionCommands = commands.filter((c) => c.category === 'actions');
	$: navigationCommands = commands.filter((c) => c.category === 'navigation');

	function handleSelect(cmd: CommandType) {
		$commandPaletteOpen = false;
		search = '';
		cmd.action();
	}
</script>

<Command.Dialog
	bind:open={$commandPaletteOpen}
	bind:value={search}
>
	<Command.Input placeholder="Type a command or search..." bind:value={search} />
	<Command.List>
		<Command.Empty>No matching commands</Command.Empty>

		{#if actionCommands.length > 0}
			<Command.Group heading="Actions">
				{#each actionCommands as cmd (cmd.id)}
					<Command.Item
						value={cmd.id}
						keywords={cmd.keywords}
						onSelect={() => handleSelect(cmd)}
					>
						<ZapIcon class="size-4 text-muted-foreground" />
						<span>{cmd.label}</span>
						{#if cmd.shortcut}
							<Command.Shortcut>{cmd.shortcut}</Command.Shortcut>
						{/if}
					</Command.Item>
				{/each}
			</Command.Group>
		{/if}

		{#if navigationCommands.length > 0}
			<Command.Group heading="Navigation">
				{#each navigationCommands as cmd (cmd.id)}
					{#if cmd.href}
						<Command.LinkItem
							value={cmd.id}
							keywords={cmd.keywords}
							href={cmd.href}
							onSelect={() => handleSelect(cmd)}
						>
							<ArrowRightIcon class="size-4 text-muted-foreground" />
							<span>{cmd.label}</span>
							{#if cmd.shortcut}
								<Command.Shortcut>{cmd.shortcut}</Command.Shortcut>
							{/if}
						</Command.LinkItem>
					{:else}
						<Command.Item
							value={cmd.id}
							keywords={cmd.keywords}
							onSelect={() => handleSelect(cmd)}
						>
							<ArrowRightIcon class="size-4 text-muted-foreground" />
							<span>{cmd.label}</span>
							{#if cmd.shortcut}
								<Command.Shortcut>{cmd.shortcut}</Command.Shortcut>
							{/if}
						</Command.Item>
					{/if}
				{/each}
			</Command.Group>
		{/if}
	</Command.List>
</Command.Dialog>
