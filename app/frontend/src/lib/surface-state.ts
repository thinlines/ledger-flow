import { derived, writable } from 'svelte/store';

/**
 * Per-surface navigation memory (CONTEXT.md: "durable surface").
 *
 * A durable surface keeps its state while the user is away: navigating back
 * to Transactions — via `g t`, the sidebar, or the palette — restores the
 * filters exactly as they were left, and navigating to the surface you are
 * already on is a no-op rather than a state-destroying reset. The URL stays
 * the source of truth for filters; this module only remembers the last URL
 * each surface produced.
 */

export type Surface = 'dashboard' | 'transactions' | 'import';

const SURFACE_ROOTS: Record<Surface, string> = {
	dashboard: '/',
	transactions: '/transactions',
	import: '/import'
};

const lastUrls = writable<Partial<Record<Surface, string>>>({});

/** Last-visited href per surface, falling back to each surface's root. */
export const surfaceHrefs = derived(lastUrls, (urls): Record<Surface, string> => {
  const out = {} as Record<Surface, string>;
  for (const surface of Object.keys(SURFACE_ROOTS) as Surface[]) {
    out[surface] = urls[surface] ?? SURFACE_ROOTS[surface];
  }
  return out;
});

/** The surface a pathname belongs to, or null for non-surface routes. */
export function surfaceForPathname(pathname: string): Surface | null {
  for (const [surface, root] of Object.entries(SURFACE_ROOTS) as [Surface, string][]) {
    if (pathname === root || pathname.startsWith(`${root}/`)) return surface;
  }
  return null;
}

/** Record the current URL (path + query) against the surface it belongs to. */
export function rememberSurfaceUrl(url: string): void {
  const pathname = url.split('?')[0];
  const surface = surfaceForPathname(pathname);
  if (!surface) return;
  lastUrls.update((urls) => ({ ...urls, [surface]: url }));
}

/** Test seam: forget everything. */
export function resetSurfaceState(): void {
  lastUrls.set({});
}
