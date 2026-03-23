# Current Task

## Objective

Make the import flow safe and recoverable when a user picks the wrong account for a CSV. A mismatched statement should be caught before it strands the user in the inbox, and the upload path should feel simpler with fewer clicks and one obvious next action.

## Current Failure

- On March 22, 2026, a user can move from import preview to upload successfully even when the selected account does not match the CSV.
- The later inbox-to-import step then fails because the file is invalid for that account.
- The user cannot remove the bad file from the inbox through the product UI, which leaves a dead-end recovery path.
- The current upload path asks the user to move through too many steps before the product confirms that the file and account actually belong together.

## Scope Cut Line

### Must Have

- Validate account-to-CSV compatibility before a file is committed to the inbox, or block the upload with clear recovery guidance before the user reaches a dead end.
- Preserve preview-before-apply safety while reducing unnecessary clicks between file selection, account selection, validation, and preview.
- Let the user remove an invalid or unwanted file from the inbox inside the UI without touching workspace files manually.
- If a mismatch is only discovered after inbox entry, show a clear recovery state with remove and retry actions instead of a generic import error.
- Keep idempotent import, conflict visibility, archive behavior, and undo support intact.
- Keep setup's inline first-import path aligned with `/import` so the same mistake does not survive in one flow but not the other.

### Should Have

- Make the import screen hierarchy clearer so one dominant action carries the user from upload into a valid preview state.
- Use plain-language error copy that explains what is wrong with the file or account choice and what to do next.
- Offer a more direct retry path after a mismatch so the user can correct the account choice without rethinking the whole workflow.

### Later

- Automatic account detection across all CSV formats
- Broader inbox management beyond the remove-and-retry actions needed for this recovery path
- A wider redesign of import history, archive browsing, or importer configuration

## Success Criteria

- A user cannot strand a mismatched CSV in the inbox by choosing the wrong account during upload.
- A bad file is either blocked before inbox commit or can be removed from the inbox in one obvious in-product action.
- The default upload path uses fewer clicks than the current preview-to-upload flow while still preserving preview before apply.
- Error states explain what happened and how to recover without exposing workspace-file or ledger internals.
- Wrong-account, valid-account, duplicate, and conflict cases all remain understandable and safe in both `/import` and setup's inline first-import flow.
- This work lands without weakening the existing audit trail or changing the `new` / `duplicate` / `conflict` model.

## Risks and Open Questions

- Confirm where account-to-CSV mismatch validation can run reliably today: before inbox write, during preview normalization, or only during import preparation for some profiles.
- Decide whether removing a bad inbox file should delete it, move it to a rejected/archive location, or mark it failed while preserving provenance.
- Confirm whether fewer clicks should come from collapsing preview and upload into one guided step or from removing secondary confirmation states around the existing flow.

## Proposed Sequence

1. Map the current failure path in `/import` and setup's inline import so validation, inbox write, and error handling happen at the same points in both flows.
2. Add the minimum product and backend behavior that prevents or recovers from wrong-account uploads without weakening import safety invariants.
3. Tighten the upload UI so the next action is obvious and the user reaches either a valid preview or a clear recovery state with less friction.
4. Verify the main cases end to end: valid upload, wrong-account mismatch, inbox removal, duplicate import, and conflict handling.

## Out of Scope

- Replacing the import pipeline architecture
- Changing import identity or provenance metadata
- Broad setup redesign outside the shared import interaction
- New importer/profile systems that are not required to solve this recovery gap

## Replacement Rule

Replace this file when the next active engineering task begins.
