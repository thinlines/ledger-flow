# Testing Heuristics

Tests in this project use pytest with real file I/O against `tmp_path` fixtures — no mocks. Follow these guidelines:

## When to write tests

- **Bug fixes:** Write the failing test first. The test encodes the broken invariant; the fix makes it pass. This order prevents "fix the symptom, miss the cause" regressions.
- **New behavior:** Test the contract (inputs → outputs) at the service-function boundary, not the internal implementation. If `build_account_register` should exclude bilateral matches, assert on the returned register, not on an internal helper's intermediate list.
- **Refactors:** Run the existing test suite before and after. If coverage is thin in the area you are changing, add characterization tests that lock current behavior before restructuring.

## How to write tests

- Use `tmp_path` to create isolated workspace directories. Write realistic journal entries and config files as fixtures — the same format the production code reads.
- Use setup helpers (like the existing `_make_config` pattern) to reduce boilerplate. Keep helpers in the test file unless multiple test files need them, then promote to `conftest.py`.
- Test one behavior per test function. Name the test after the behavior: `test_bilateral_match_excludes_both_from_pending`, not `test_register_3`.
- Cover edge cases called out in `TASK.md` explicitly. Each edge case in the task spec should map to at least one test.

## What not to test

- Do not mock the file system, the journal parser, or service internals. The journal file *is* the test fixture; mocking it removes the value of the test.
- Do not write tests for trivial getters, dataclass construction, or framework boilerplate.
- Do not add tests for code you did not change unless the existing coverage is dangerously thin for the area you are working in.
