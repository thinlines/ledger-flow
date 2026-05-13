import { writable } from 'svelte/store';

export type EntryModalState = {
	open: boolean;
	sessionCount: number;
	lastAccountId: string | null;
};

export const entryModal = writable<EntryModalState>({
	open: false,
	sessionCount: 0,
	lastAccountId: null
});

export function openEntryModal(preselectedAccountId?: string) {
	entryModal.update((s) => ({
		...s,
		open: true,
		lastAccountId: preselectedAccountId ?? s.lastAccountId
	}));
}

export function closeEntryModal() {
	entryModal.update((s) => ({ ...s, open: false }));
}

export function incrementSession() {
	entryModal.update((s) => ({ ...s, sessionCount: s.sessionCount + 1 }));
}

export function setLastAccount(accountId: string) {
	entryModal.update((s) => ({ ...s, lastAccountId: accountId }));
}
