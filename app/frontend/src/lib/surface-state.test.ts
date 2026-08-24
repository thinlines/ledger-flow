import { get } from 'svelte/store';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  rememberSurfaceUrl,
  resetSurfaceState,
  surfaceHrefs,
  surfaceForPathname
} from './surface-state';

beforeEach(() => resetSurfaceState());

describe('surface state — remembering where the user left each surface', () => {
  it('falls back to the surface root before any visit', () => {
    expect(get(surfaceHrefs).dashboard).toBe('/');
    expect(get(surfaceHrefs).transactions).toBe('/transactions');
  });

  it('returns the last visited URL for the surface, filters intact', () => {
    rememberSurfaceUrl('/transactions?accounts=chase&period=last-30&q=coffee');
    expect(get(surfaceHrefs).transactions).toBe(
      '/transactions?accounts=chase&period=last-30&q=coffee'
    );
  });

  it('keeps only the most recent state', () => {
    rememberSurfaceUrl('/transactions?period=last-30');
    rememberSurfaceUrl('/transactions?q=rent');
    expect(get(surfaceHrefs).transactions).toBe('/transactions?q=rent');
  });

  it('ignores URLs that belong to no known surface', () => {
    rememberSurfaceUrl('/definitely-not-a-surface?x=1');
    expect(get(surfaceHrefs).transactions).toBe('/transactions');
  });
});

describe('surface state — resolving the current surface', () => {
  it('maps a surface pathname (with or without subpaths) to its surface', () => {
    expect(surfaceForPathname('/')).toBe('dashboard');
    expect(surfaceForPathname('/transactions')).toBe('transactions');
    expect(surfaceForPathname('/transactions/anything')).toBe('transactions');
  });

  it('maps unknown pathnames to null', () => {
    expect(surfaceForPathname('/transactions-export')).toBeNull();
  });
});
