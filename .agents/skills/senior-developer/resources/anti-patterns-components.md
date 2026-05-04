# Component and UI Anti-Patterns (Svelte / Astro)

- Do not put non-trivial expressions inline in template blocks (`{#each}`, `{#if}`, attribute bindings). Move the logic into a named variable or function in the `<script>` block where it can be read, tested, and reused.
- Do not let a single component file grow past the point where its responsibilities are obvious. Extract sub-components or move shared logic into `$lib/` modules that both components and pages can import.
- Do not duplicate types that mirror backend models across multiple route files. Define them once in a shared location and import them.
