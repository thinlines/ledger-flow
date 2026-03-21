# UI Review Rubric

Use this reference when turning a visual review into a findings report.

## Severity

- `Critical`: Blocks a core task, creates a serious trust problem, or is likely to cause a damaging action.
- `High`: The flow still works, but confusion, friction, or ambiguity is bad enough to threaten adoption or completion.
- `Medium`: Noticeable friction, weak hierarchy, or unclear copy slows the user down, but a workaround exists.
- `Low`: Localized polish or consistency issue with limited impact on task completion.

## Audit Lenses

### Clarity and next action

Ask:

- Can a first-time user tell what this screen is for?
- Is the dominant next action obvious above the fold?
- Does anything compete with or dilute the main task?

### Hierarchy and scanability

Ask:

- Does the layout guide the eye in the right order?
- Is important information easy to scan?
- Are dense tables, cards, or controls forcing too much interpretation?

### Copy and terminology

Ask:

- Is the language plain and finance-first?
- Does the UI leak ledger, journal, path, or implementation terms?
- Do labels and helper text explain the user outcome rather than the system structure?

### Trust and feedback

Ask:

- Can the user tell what data they are looking at and how current it is?
- Are loading, success, warning, and failure states visible and believable?
- Does the UI create doubt about whether an action worked?

### Empty, error, and success states

Ask:

- Do empty states explain what to do next?
- Do errors explain how to recover?
- Does success feedback close the loop and point to the next step?

### Responsiveness and ergonomics

Ask:

- Does the layout still hold together on narrow screens?
- Are actions easy to reach without precision clicking?
- Do sticky areas, dialogs, or tables make the flow awkward on mobile?

### Accessibility basics

Ask:

- Is contrast sufficient for status and primary actions?
- Is focus visible?
- Can the main flow be understood and used with keyboard navigation?

## Finding Format

Use this shape for each finding:

1. `Severity - Route/Screen - Short title`
2. `Observed` or `Inferred`
3. Why it matters
4. Recommended improvement

Keep each finding concrete. Avoid abstract design commentary without a user-facing consequence.

## Output Shape

### Findings

- List the issues first, ordered by severity.
- Include route, state, and evidence for each item.

### What Works

- Preserve a short list of decisions worth keeping when they support the product direction.

### PM Digest

- Convert the top findings into `Now`, `Next`, and `Later`.
- For each item, say what it protects: comprehension, trust, task completion, or polish.
- If a fix expands scope, say what should be deferred instead.

### Review Limits

- State what was not reviewed, what was inferred, and any missing environments or device coverage.
