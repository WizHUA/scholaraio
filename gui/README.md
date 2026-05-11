# ScholarAIO GUI Boundary

`gui/` is reserved for the future presentation shell.

This directory may contain web, desktop, or other UI-facing code later, but it is intentionally empty of business behavior for now.

Boundary rules:

- GUI code MUST remain presentation-oriented.
- GUI code MUST NOT become the source of truth for runtime layout, migration behavior, ingest rules, or research-library semantics.
- GUI code should call stable service or interface adapters instead of reading runtime directories directly.
