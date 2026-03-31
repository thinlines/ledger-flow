# Ledger Flow UI Direction

## Contents

- Product feel
- Visual system
- Layout priorities
- Route emphasis map
- Anti-patterns

## Product Feel

Ledger Flow should feel like a polished personal finance workspace, not an admin console and not a generic component-library demo.

Hold these tensions at the same time:

- Bold enough to feel designed on purpose
- Familiar enough that a nontechnical user never hesitates over basic actions
- Calm enough to handle money without theatrics
- Consistent enough that screens feel related even when their workflows differ

## Visual System

### Typography

- Use `Space Grotesk` for headings and section-defining moments.
- Use `Inter` for body text, labels, tables, helper text, and controls.
- Let headings create personality. Let body text stay quiet and dependable.

### Color

- Treat deep blue-green as the main brand anchor.
- Use the mint-tinted background and soft blue highlights to keep the app airy rather than stark.
- Use amber for attention and red for destructive or error states.
- Keep green and blue distinct when representing income vs spending or positive vs structural information.

Current core tokens from `app/frontend/src/app.css`:

- `--bg: #f4f4ea`
- `--bg-accent: #edf6ef`
- `--brand: #0f5f88`
- `--brand-strong: #0a3d59`
- `--ok: #0d7f58`
- `--warn: #ad6a00`
- `--bad: #b73a3a`
- `--shadow: 0 16px 34px rgba(16, 33, 51, 0.08)`

### Surfaces

- Prefer elevated cards, soft borders, blur, and gentle gradients over flat white slabs.
- Use gradients with restraint. Reserve the strongest gradient treatment for hero moments, primary actions, and brand marks.
- Keep corner radius generous and friendly, but consistent across the app.

### Interaction

- Preserve standard control behavior. Buttons should behave like buttons, disclosures like disclosures, tables like tables.
- Put originality into hierarchy, section framing, density control, and information pacing.
- Give important states a clear visual signature without turning the whole screen into a status rainbow.

## Layout Priorities

- Each screen needs a dominant focal point and a fast scan path.
- Keep one primary action per screen.
- Compress secondary or structural information before compressing the user’s next action.
- Prefer a few well-shaped sections over many same-weight boxes.
- On mobile, stack cleanly into a single confident column instead of shrinking everything uniformly.

## Route Emphasis Map

### Overview

- Lead with current position, recent movement, and the next meaningful action.
- Make summary information feel trustworthy and scannable.
- Keep structural finance views lower priority than immediate daily-use cues.

### Accounts

- Emphasize trust, completeness, and clear setup status.
- Make tracked accounts feel tangible and understandable.

### Transactions

- Prioritize scanability, status clarity, and dense-but-readable activity.
- Avoid ornamental noise around tabular information.

### Import and Review

- Emphasize progress, safety, and the next action.
- Reduce cognitive load when the user is resolving uncertainty.

### Setup

- Feel guided and reassuring, not infrastructural.
- Keep the path forward obvious at every step.

## Anti-Patterns

- Generic shadcn-looking stacks of identical white cards with no hierarchy
- Visual novelty that changes control behavior or makes actions harder to predict
- Route-local color inventions that ignore the existing blue-green, mint, amber, and red palette
- Too many chips, badges, or pills competing for attention
- Copy that exposes ledger, journal, file, or account-wiring internals in default flows
- Equal visual weight across all stats, panels, and actions
- Dense diagnostics on primary screens when a summary and a next step would be clearer
