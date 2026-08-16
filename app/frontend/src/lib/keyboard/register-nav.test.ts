import { describe, expect, it } from 'vitest';
import { nextId, prevId, reconcileFocus } from './register-nav';

const ids = ['a', 'b', 'c', 'd'];

describe('register roving focus — movement', () => {
  it('j from nothing focuses the first row', () => {
    expect(nextId(ids, null)).toBe('a');
  });

  it('k from nothing also focuses the first row (predictable entry point)', () => {
    expect(prevId(ids, null)).toBe('a');
  });

  it('j and k step through neighbours', () => {
    expect(nextId(ids, 'b')).toBe('c');
    expect(prevId(ids, 'b')).toBe('a');
  });

  it('clamps at both ends instead of wrapping', () => {
    expect(nextId(ids, 'd')).toBe('d');
    expect(prevId(ids, 'a')).toBe('a');
  });

  it('an empty register has nothing to focus', () => {
    expect(nextId([], null)).toBeNull();
    expect(prevId([], null)).toBeNull();
  });

  it('a stale focus id recovers to the first row', () => {
    expect(nextId(ids, 'gone')).toBe('a');
  });
});

describe('register roving focus — surviving reloads', () => {
  it('keeps focus on the same row when it is still present', () => {
    expect(reconcileFocus(ids, ['b', 'c', 'd'], 'c')).toBe('c');
  });

  it('moves focus to the row that took the deleted row’s place', () => {
    // 'b' deleted: position 1 in the new list is 'c'.
    expect(reconcileFocus(ids, ['a', 'c', 'd'], 'b')).toBe('c');
  });

  it('falls back to the last row when the tail was deleted', () => {
    expect(reconcileFocus(ids, ['a', 'b'], 'd')).toBe('b');
  });

  it('clears focus when the register empties', () => {
    expect(reconcileFocus(ids, [], 'b')).toBeNull();
  });

  it('leaves an unset focus unset', () => {
    expect(reconcileFocus(ids, ids, null)).toBeNull();
  });
});
