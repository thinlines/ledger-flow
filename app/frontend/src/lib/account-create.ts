/**
 * Create-account flow helpers: the modal collects a parent account (picked
 * from projected data) and a new leaf name; the backend composes and
 * declares the fully qualified account.
 */

export interface AccountSeed {
	parent: string;
	leaf: string;
}

/** Split a combobox "create …" seed into parent + leaf. A bare name seeds
 * only the leaf; a fully qualified name pre-fills the parent picker. */
export function splitAccountSeed(seed: string): AccountSeed {
	const trimmed = seed.trim();
	const lastColon = trimmed.lastIndexOf(':');
	if (lastColon === -1) return { parent: '', leaf: trimmed };
	return {
		parent: trimmed.slice(0, lastColon).trim(),
		leaf: trimmed.slice(lastColon + 1).trim()
	};
}

/** Client-side mirror of the backend's parent+leaf validation; returns the
 * error copy to show, or null when submittable. */
export function validateNewAccount(parent: string, leaf: string): string | null {
	if (!parent.trim()) return 'Choose a parent account.';
	if (!leaf.trim()) return 'Enter a name for the new account.';
	if (leaf.includes(':')) return "The name cannot contain ':' — pick a deeper parent instead.";
	return null;
}
