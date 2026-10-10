<script lang="ts">
	import { tick } from 'svelte';
	import { ACCOUNT_SUBTYPE_OPTIONS } from '$lib/account-subtypes';
	import { apiPost } from '$lib/api';
	import { parseAmount } from '$lib/currency-parser';
	import Building2 from '@lucide/svelte/icons/building-2';
	import CreditCard from '@lucide/svelte/icons/credit-card';
	import Landmark from '@lucide/svelte/icons/landmark';
	import Pencil from '@lucide/svelte/icons/pencil';
	import Plus from '@lucide/svelte/icons/plus';
	import X from '@lucide/svelte/icons/x';

	type Kind = 'asset' | 'liability';
	type Account = {
		id: string;
		displayName: string;
		kind: Kind;
		subtype: string | null;
		institutionId: string | null;
		institutionDisplayName: string | null;
		last4: string | null;
		ledgerAccount: string;
		openingBalance: string | null;
		openingBalanceDate: string | null;
		minimumPayment: string | null;
	};
	type InstitutionTemplate = { id: string; displayName: string; suggestedLedgerPrefix: string };
	type Draft = {
		displayName: string;
		kind: Kind;
		subtype: string;
		institutionId: string;
		last4: string;
		openingBalance: string;
		openingDate: string;
		minimumPayment: string;
	};

	export let institutionTemplates: InstitutionTemplate[] = [];
	export let existingAccounts: Pick<Account, 'id' | 'ledgerAccount'>[] = [];
	export let baseCurrency = 'USD';
	export let onSaved: (accountId: string) => void = () => {};

	let open = false;
	let editingAccount: Account | null = null;
	let draft = freshDraft();
	let saving = false;
	let error = '';
	let nameInput: HTMLInputElement | null = null;
	$: subtypeOptions = ACCOUNT_SUBTYPE_OPTIONS.filter((option) => option.kind === draft.kind);
	$: selectedSubtype = subtypeOptions.find((option) => option.value === draft.subtype);

	function today() {
		const date = new Date();
		return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
	}

	function freshDraft(): Draft {
		return {
			displayName: '',
			kind: 'asset',
			subtype: 'checking',
			institutionId: '',
			last4: '',
			openingBalance: '',
			openingDate: today(),
			minimumPayment: ''
		};
	}

	function draftFromAccount(account: Account): Draft {
		return {
			displayName: account.displayName,
			kind: account.kind,
			subtype: account.subtype ?? (account.kind === 'liability' ? 'credit_card' : 'checking'),
			institutionId: account.institutionId ?? '',
			last4: account.last4 ?? '',
			openingBalance: account.openingBalance == null
				? ''
				: account.kind === 'liability'
					? account.openingBalance.replace(/^-/, '')
					: account.openingBalance,
			openingDate: account.openingBalanceDate ?? today(),
			minimumPayment: account.minimumPayment ?? ''
		};
	}

	function chooseKind(kind: Kind) {
		draft.kind = kind;
		draft.subtype = kind === 'liability' ? 'credit_card' : 'checking';
	}

	function openAdd() {
		editingAccount = null;
		draft = freshDraft();
		error = '';
		open = true;
		void focusName();
	}

	function openEdit(account: Account) {
		editingAccount = account;
		draft = draftFromAccount(account);
		error = '';
		open = true;
		void focusName();
	}

	export { openAdd, openEdit };

	async function focusName() {
		await tick();
		nameInput?.focus();
	}

	function close() {
		if (saving) return;
		open = false;
	}

	function normalizedAmount(raw: string, kind: Kind, liabilityCredit = false) {
		if (!raw.trim()) return '';
		let value: string;
		try {
			value = parseAmount(raw);
		} catch {
			throw new Error('Enter a valid amount.');
		}
		if (kind !== 'liability' || !liabilityCredit) return value;
		const magnitude = value.replace(/^-/, '');
		return magnitude === '0' || /^0(?:\.0+)?$/.test(magnitude) ? '0' : `-${magnitude}`;
	}

	function ledgerSegment(value: string) {
		return value.trim().split(/[^A-Za-z0-9]+/).filter(Boolean).map((part) => part[0].toUpperCase() + part.slice(1)).join('');
	}

	function ledgerAccountForDraft() {
		const root = draft.kind === 'liability' ? 'Liabilities' : 'Assets';
		if (editingAccount) {
			const [, ...rest] = editingAccount.ledgerAccount.split(':');
			return [root, ...rest].join(':');
		}
		const template = institutionTemplates.find((item) => item.id === draft.institutionId);
		const templateParts = template?.suggestedLedgerPrefix.split(':').slice(1).map(ledgerSegment) ?? [];
		const subtypeGroup: Record<string, string> = {
			checking: 'Bank', savings: 'Bank', cash: 'Cash', investment: 'Investments',
			vehicle: 'Vehicle', real_estate: 'Property', other_asset: 'Other',
			credit_card: 'CreditCard', loan: 'Loans', mortgage: 'Mortgage', other_liability: 'Other'
		};
		const accountGroup = templateParts.length ? templateParts : [subtypeGroup[draft.subtype] ?? 'Other'];
		const base = [root, ...accountGroup, ledgerSegment(draft.displayName)].filter(Boolean).join(':');
		let candidate = base;
		let suffix = 2;
		while (existingAccounts.some((account) => account.ledgerAccount === candidate)) {
			candidate = `${base}${suffix}`;
			suffix += 1;
		}
		return candidate;
	}

	function money(raw: string) {
		const amount = Number(raw.replace(/[$,]/g, ''));
		if (!raw.trim() || !Number.isFinite(amount)) return '—';
		return new Intl.NumberFormat(undefined, { style: 'currency', currency: baseCurrency, maximumFractionDigits: 2 }).format(Math.abs(amount));
	}

	async function save() {
		error = '';
		saving = true;
		try {
			const result = await apiPost<{ trackedAccount: { id: string } }>('/api/tracked-accounts', {
				accountId: editingAccount?.id ?? null,
				displayName: draft.displayName.trim(),
				ledgerAccount: ledgerAccountForDraft(),
				subtype: draft.subtype,
				institutionId: draft.institutionId || null,
				last4: draft.last4.trim() || null,
				openingBalance: normalizedAmount(draft.openingBalance, draft.kind, true),
				openingBalanceDate: draft.openingDate || null,
				minimumPayment: normalizedAmount(draft.minimumPayment, 'asset')
			});
			open = false;
			onSaved(result.trackedAccount.id);
		} catch (caught) {
			error = caught instanceof Error ? caught.message : String(caught);
		} finally {
			saving = false;
		}
	}
</script>

{#if open}
	<button class="fixed inset-0 z-40 cursor-default border-0 bg-black/30" aria-label="Close account modal" on:click={close}></button>
	<div class="pointer-events-none fixed inset-0 z-40 grid place-items-center px-4 py-6" role="dialog" aria-modal="true" aria-labelledby="account-modal-title">
		<form class="pointer-events-auto flex max-h-[calc(100vh-3rem)] min-h-[36rem] w-full max-w-4xl flex-col overflow-hidden rounded-xl border border-hairline-strong bg-panel shadow-xl max-sm:min-h-0" on:submit|preventDefault={save}>
			<header class="flex shrink-0 items-center justify-between border-b px-6 py-4"><div class="flex items-center gap-3"><span class="grid size-9 place-items-center rounded-lg bg-brand-wash text-brand-deep">{#if editingAccount}<Pencil size={16}/>{:else}<Plus size={17}/>{/if}</span><h2 id="account-modal-title" class="m-0 font-display text-lg font-semibold">{editingAccount ? `Edit ${editingAccount.displayName}` : 'New account'}</h2></div><button type="button" class="rounded-md border-0 bg-transparent p-1 text-ink-mute hover:bg-wash" aria-label="Close" disabled={saving} on:click={close}><X size={18}/></button></header>
			<div class="min-h-0 flex-1 overflow-y-auto"><div class="grid md:grid-cols-[minmax(0,1fr)_19rem]">
				<div class="grid content-start gap-5 border-r p-6 max-md:border-r-0 max-md:border-b">
					<fieldset class="grid grid-cols-2 gap-2"><legend class="mb-2 text-xs font-medium text-ink-mute">Account type</legend><button type="button" class="flex items-center gap-2 rounded-lg border p-2.5 text-left {draft.kind === 'asset' ? 'border-brand bg-brand-wash text-brand-deep' : 'bg-panel hover:bg-wash'}" aria-pressed={draft.kind === 'asset'} on:click={() => chooseKind('asset')}><Landmark size={16}/><span class="text-sm font-medium">Money I have</span></button><button type="button" class="flex items-center gap-2 rounded-lg border p-2.5 text-left {draft.kind === 'liability' ? 'border-brand bg-brand-wash text-brand-deep' : 'bg-panel hover:bg-wash'}" aria-pressed={draft.kind === 'liability'} on:click={() => chooseKind('liability')}><CreditCard size={16}/><span class="text-sm font-medium">Money I owe</span></button></fieldset>
					<label class="text-xs font-medium text-ink-mute">Display name<input bind:this={nameInput} class="mt-1.5" bind:value={draft.displayName} placeholder="Everyday checking" required /></label>
					<div class="grid grid-cols-2 gap-4 max-sm:grid-cols-1"><label class="text-xs font-medium text-ink-mute">Subtype<select class="mt-1.5" bind:value={draft.subtype}>{#each subtypeOptions as option}<option value={option.value}>{option.longLabel}</option>{/each}</select></label><label class="text-xs font-medium text-ink-mute">Institution <span class="font-normal">(optional)</span><select class="mt-1.5" bind:value={draft.institutionId}><option value="">None</option>{#each institutionTemplates as template}<option value={template.id}>{template.displayName}</option>{/each}</select></label></div>
					<div class="grid grid-cols-3 gap-4 max-sm:grid-cols-1"><label class="text-xs font-medium text-ink-mute">Last 4 <span class="font-normal">(optional)</span><input class="mt-1.5" bind:value={draft.last4} inputmode="numeric" maxlength="4" placeholder="1234" /></label><label class="text-xs font-medium text-ink-mute">Opening balance <span class="font-normal">(optional)</span><input class="amount mt-1.5" bind:value={draft.openingBalance} inputmode="decimal" placeholder="0.00" /></label><label class="text-xs font-medium text-ink-mute">Balance date<input class="mt-1.5" type="date" bind:value={draft.openingDate} /></label></div>
					{#if draft.kind === 'liability'}<label class="max-w-44 text-xs font-medium text-ink-mute">Minimum payment <span class="font-normal">(optional)</span><input class="amount mt-1.5" bind:value={draft.minimumPayment} inputmode="decimal" placeholder="0.00" /></label>{:else}<div class="invisible h-[3.75rem]" aria-hidden="true"></div>{/if}
				</div>
				<aside class="bg-wash p-6"><p class="mb-4 text-[0.6875rem] font-semibold uppercase tracking-wider text-ink-mute">Preview</p><div class="rounded-xl border bg-panel p-4"><div class="flex items-start gap-3"><span class="grid size-9 place-items-center rounded-lg bg-wash">{#if draft.kind === 'liability'}<CreditCard size={16}/>{:else if draft.subtype === 'vehicle' || draft.subtype === 'real_estate'}<Building2 size={16}/>{:else}<Landmark size={16}/>{/if}</span><div class="min-w-0"><p class="truncate font-medium">{draft.displayName || 'Untitled account'}</p><p class="text-xs text-ink-mute">{selectedSubtype?.label ?? 'Account'}{draft.last4 ? ` · •${draft.last4}` : ''}</p></div></div><dl class="mt-5 grid gap-3 border-t pt-4 text-xs"><div><dt class="text-ink-mute">Institution</dt><dd class="mt-0.5">{institutionTemplates.find((item) => item.id === draft.institutionId)?.displayName ?? '—'}</dd></div><div><dt class="text-ink-mute">Opening balance</dt><dd class="amount mt-0.5">{money(draft.openingBalance)}</dd></div><div class:invisible={!draft.openingBalance}><dt class="text-ink-mute">Balance date</dt><dd class="mt-0.5">{draft.openingDate || '—'}</dd></div><div class:invisible={draft.kind !== 'liability'}><dt class="text-ink-mute">Minimum payment</dt><dd class="amount mt-0.5">{money(draft.minimumPayment)}</dd></div></dl></div></aside>
			</div></div>
			<footer class="flex shrink-0 items-center justify-between gap-4 border-t px-6 py-4"><p class="m-0 min-w-0 truncate text-xs text-bad" role="alert">{error}</p><div class="flex shrink-0 gap-2"><button type="button" class="rounded-md border bg-panel px-3 py-1.5 text-sm" disabled={saving} on:click={close}>Cancel</button><button type="submit" class="rounded-md border border-brand bg-brand px-4 py-1.5 text-sm font-medium text-white disabled:opacity-60" disabled={saving}>{saving ? 'Saving…' : editingAccount ? 'Save changes' : 'Create account'}</button></div></footer>
		</form>
	</div>
{/if}
