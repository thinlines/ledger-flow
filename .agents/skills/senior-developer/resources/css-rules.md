# CSS / Tailwind Rules

The codebase uses Tailwind v4 utility-first design. All new styling must follow this approach. Do not add scoped `<style>` blocks for layout, typography, spacing, or colors that have utility equivalents.

## When to use template utilities (the default)

- Grids, flexbox, gaps, paddings, margins, widths, min/max sizing
- Font size, weight, family (`font-display` for Space Grotesk), line-height, letter-spacing, text-transform
- Colors that map to theme tokens: `text-brand-strong`, `bg-ok`, `border-card-edge`, `text-muted-foreground`, etc.
- Responsive layout changes via the theme breakpoints: `max-tablet:` (720px), `max-shell:` (980px), `max-desktop:` (1100px)
- Opacity modifiers on named colors: `bg-white/80`, `border-brand/20`

## When scoped `<style>` is acceptable

- Multi-stop or layered CSS gradients (`linear-gradient`, `radial-gradient`) that have no utility equivalent
- State variants (`class:active`, `class:expanded`, etc.) that change multiple bespoke properties (border-color + box-shadow + transform) together — keep only the bespoke overrides scoped, not the base layout
- Adjacent-sibling separator rules (`.row + .row { border-top }`) — cleaner than `[&+&]:` utility chains
- Segmented controls with active/hover states and custom shadows
- Bespoke widget styling (clearing-status circles, drag-handle dot grids, CSS-rotate chevrons) that would require many arbitrary values to express inline

## Rules

- Minimize arbitrary bracket values (`w-[33px]`, `text-[0.82rem]`). Use the closest Tailwind default when within ~1px. Brackets are acceptable for asymmetric `grid-cols-[...]`, `clamp()` font sizes, and `min()`/`calc()` widths.
- Use canonical Tailwind v4 class names: `wrap-anywhere` not `[overflow-wrap:anywhere]`, `w-2xl` not `w-[42rem]`.
- Use existing component classes from `app.css` (`view-card`, `eyebrow`, `page-title`, `subtitle`, `btn`, `btn-primary`, `pill`, `field`, `text-link`, `muted`, `error-text`) — do not inline what a named class already provides.
- For bits-ui portaled content (Dialog, Popover, etc.), pass Tailwind utilities via the `class` prop on the primitive — do not use `:global()` selectors in scoped style. Utilities are global by nature and cross portals without escapes.
- When a scoped `<style>` block is needed, keep it minimal: only the properties that genuinely cannot be expressed as utilities. Put structural layout (grid, flex, gap, padding) on the element as utilities even if the element also has a scoped class for its bespoke properties.
- Drop local class definitions that duplicate globals (`.muted`, `.small`, `.text-link`). Use the global version or inline utilities.
- For repeated button class lists in a single file, use a `const btnClass = '...'` variable in the script block rather than falling back to a scoped CSS class — stays utility-first and DRY.
