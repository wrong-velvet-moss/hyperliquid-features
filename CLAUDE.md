# Instructions

Whenever corrected, after making a mistake or misinterpreting, add a section in here (`CLAUDE.md`) to instruct future sessions, avoiding the mistake again.

ALWAYS use subagents where possible, parralell work is better.

## Tools

ALWAYS use `uv` in python. `uv add` for installs, NEVER `pip install` directly.
`uv run example.py` for running, NEVER `python example.py` or `python3 example.py` directly.
Avoid editing the `pyproject.toml` directly, where possible use `uv add`, `uv remove` etc.

Use `ruff` for formatting python files, run via `uv run ruff`. Run `ruff check` on any new files before running them or including them. Fix any warnings or errors before proceeding.

Run type checking with `ty` on all new code. run via `uv run ty` only on the edited file(s). Always run after any changes to python code, fix the errors before proceeding, avoid suppressing types where possible (e.g. `# noqa`, `# type: ignore`).

## Guidelines

- Use google docstring format
- Follow SOLID design principles where possible
- we do not care about test coverage too much, functionality is most important.
- if writing unit tests, always use `pytest`, run via `uv run pytest`
