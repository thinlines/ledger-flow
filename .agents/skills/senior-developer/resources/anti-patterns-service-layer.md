# Service Layer Anti-Patterns (Python / FastAPI)

- Do not reach into `AppConfig` internals from multiple unrelated call sites. Access configuration through the service function that owns that concern.
- Do not mix file-system side effects with pure computation in the same function. Keep parsing, filtering, and transformation pure; push I/O (reads, writes, archives) to the edges.
- Do not use mutable default arguments or module-level mutable state. Prefer frozen dataclasses and explicit parameter passing.
