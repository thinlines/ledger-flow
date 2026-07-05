import { beforeEach, describe, expect, it } from 'vitest';
import {
  clearRememberedUnknownStage,
  recallUnknownStage,
  rememberUnknownStage
} from './unknown-stage-memory';

function makeStorage(): Storage {
  const data = new Map<string, string>();
  return {
    get length() {
      return data.size;
    },
    clear: () => data.clear(),
    getItem: (key: string) => data.get(key) ?? null,
    key: (index: number) => [...data.keys()][index] ?? null,
    removeItem: (key: string) => void data.delete(key),
    setItem: (key: string, value: string) => void data.set(key, value)
  };
}

const WORKSPACE = '/home/user/books';
const KEY = `ledger-flow:unknown-review:${WORKSPACE}`;

describe('unknown stage memory', () => {
  let storage: Storage;

  beforeEach(() => {
    storage = makeStorage();
  });

  it('remembers and recalls a stage per workspace', () => {
    rememberUnknownStage(WORKSPACE, { stageId: 'abc123', journalPath: '/books/2026.journal' }, storage);

    expect(recallUnknownStage(WORKSPACE, storage)).toEqual({
      stageId: 'abc123',
      journalPath: '/books/2026.journal'
    });
    expect(recallUnknownStage('/other/workspace', storage)).toBeNull();
  });

  it('remembering a null or id-less stage clears the entry', () => {
    rememberUnknownStage(WORKSPACE, { stageId: 'abc123', journalPath: '/books/2026.journal' }, storage);

    rememberUnknownStage(WORKSPACE, null, storage);
    expect(storage.getItem(KEY)).toBeNull();

    rememberUnknownStage(WORKSPACE, { stageId: 'abc123', journalPath: '/books/2026.journal' }, storage);
    rememberUnknownStage(WORKSPACE, { journalPath: '/books/2026.journal' }, storage);
    expect(storage.getItem(KEY)).toBeNull();
  });

  it('recall requires a stage id and tolerates a missing journal path', () => {
    storage.setItem(KEY, JSON.stringify({ journalPath: '/books/2026.journal' }));
    expect(recallUnknownStage(WORKSPACE, storage)).toBeNull();

    storage.setItem(KEY, JSON.stringify({ stageId: '  abc123  ' }));
    expect(recallUnknownStage(WORKSPACE, storage)).toEqual({ stageId: 'abc123', journalPath: '' });
  });

  it('corrupted JSON clears the entry and returns null', () => {
    storage.setItem(KEY, '{not json');

    expect(recallUnknownStage(WORKSPACE, storage)).toBeNull();
    expect(storage.getItem(KEY)).toBeNull();
  });

  it('no workspace path means nothing is stored or recalled', () => {
    rememberUnknownStage('', { stageId: 'abc123', journalPath: '/books/2026.journal' }, storage);
    expect(storage.length).toBe(0);
    expect(recallUnknownStage('', storage)).toBeNull();
  });

  it('clear removes the workspace entry only', () => {
    rememberUnknownStage(WORKSPACE, { stageId: 'abc123', journalPath: '/books/2026.journal' }, storage);
    rememberUnknownStage('/other', { stageId: 'zzz999', journalPath: '/other/2026.journal' }, storage);

    clearRememberedUnknownStage(WORKSPACE, storage);

    expect(recallUnknownStage(WORKSPACE, storage)).toBeNull();
    expect(recallUnknownStage('/other', storage)).toEqual({
      stageId: 'zzz999',
      journalPath: '/other/2026.journal'
    });
  });
});
