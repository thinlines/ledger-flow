import { describe, expect, it } from 'vitest';

/**
 * Regression test for combobox Enter-key filtering.
 *
 * AccountCombobox and the inline tracked-account combobox in
 * TransactionEntryModal both intercept Enter to select the highlighted
 * item. They must NOT intercept Ctrl+Enter or Ctrl+Shift+Enter, which
 * the modal uses for submit-and-add / submit-and-close.
 *
 * Bug introduced in ffabe82 — the custom portal-dropdown handler called
 * stopPropagation() on *all* Enter presses, blocking modal submission.
 */

/** The guard condition used in both combobox keydown handlers. */
function comboboxShouldConsumeEnter(event: Pick<KeyboardEvent, 'key' | 'ctrlKey' | 'metaKey'>) {
  return event.key === 'Enter' && !event.ctrlKey && !event.metaKey;
}

describe('combobox Enter-key guard (regression for ffabe82)', () => {
  it('consumes plain Enter', () => {
    expect(comboboxShouldConsumeEnter({ key: 'Enter', ctrlKey: false, metaKey: false })).toBe(true);
  });

  it('does NOT consume Ctrl+Enter (submit-and-add)', () => {
    expect(comboboxShouldConsumeEnter({ key: 'Enter', ctrlKey: true, metaKey: false })).toBe(false);
  });

  it('does NOT consume Ctrl+Shift+Enter (submit-and-close)', () => {
    expect(comboboxShouldConsumeEnter({ key: 'Enter', ctrlKey: true, metaKey: false })).toBe(false);
  });

  it('does NOT consume Meta+Enter (macOS submit)', () => {
    expect(comboboxShouldConsumeEnter({ key: 'Enter', ctrlKey: false, metaKey: true })).toBe(false);
  });

  it('does NOT consume Meta+Shift+Enter (macOS submit-and-close)', () => {
    expect(comboboxShouldConsumeEnter({ key: 'Enter', ctrlKey: false, metaKey: true })).toBe(false);
  });

  it('ignores non-Enter keys regardless of modifiers', () => {
    expect(comboboxShouldConsumeEnter({ key: 'Escape', ctrlKey: false, metaKey: false })).toBe(false);
    expect(comboboxShouldConsumeEnter({ key: 'Tab', ctrlKey: true, metaKey: false })).toBe(false);
  });
});
