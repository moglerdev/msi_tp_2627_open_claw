# CLAUDE.md

@AGENTS.md

`AGENTS.md` (imported above) is the single source of truth for project structure,
tooling and conventions. Put shared rules there, not here — this file only holds
Claude Code specifics.

## Claude Code specifics

- Personal preferences and machine-specific paths go in `CLAUDE.local.md` (gitignored),
  not in this file.
- Shared permissions/hooks go in `.claude/settings.json`; personal ones in
  `.claude/settings.local.json` (gitignored). Never put tokens or secrets in either.
- Use `uv run …` for every Python command — never call `python`/`pip` directly.
- After editing Python files, run `uv run ruff check --fix` and `uv run ruff format`
  on the changed files, then the tests of the affected member.
- Before SSH into `gpu-htwg` or the Hermes host, or before starting/stopping a model
  server, ask the user first — these are shared team resources.
- Commit only when asked, and only on a feature branch — `main` is protected and
  needs a reviewed PR (see "Git workflow" in AGENTS.md). Use Conventional Commits
  in English.
