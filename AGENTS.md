# AGENTS.md

Guidance for AI coding agents (Claude Code, Codex, Cursor, OpenCode, …) and humans
working in this repository. Keep this file short and accurate — update it in the same
PR when you change structure, tooling or conventions.

## Project

Team project MSI WS 2026/27 — **OpenClaw**. We run the OpenClaw agent against a
self-hosted LLM (vLLM, OpenAI-compatible API) and evaluate it with benchmarks on
real documents (txt, pdf, …).

Three benchmark dimensions:

1. **LLM performance** — throughput and latency (decode tok/s, prefill tok/s, TTFT).
2. **Answer quality** — agent/LLM answers to document tasks, scored against expected answers.
3. **Document extraction** — how well text/structure is extracted from PDFs and other formats.

## Repository layout (monorepo)

```
.
├── apps/                 # Runnable applications (each one a uv workspace member)
│   └── <app>/
│       ├── pyproject.toml
│       ├── src/<app>/
│       └── tests/
├── packages/             # Shared libraries used by apps and benchmarks (uv workspace members)
│   └── <pkg>/            # e.g. llm client, document loaders, scoring
├── benchmarks/
│   ├── suites/           # Benchmark definitions (perf, quality, extraction)
│   ├── datasets/         # Test files: txt, pdf, docx, … (binaries via Git LFS)
│   │   └── <dataset>/
│   │       ├── inputs/   # Source documents
│   │       ├── expected/ # Ground truth (answers, extracted text) — same base name as input
│   │       └── README.md # Source, license, what the dataset tests
│   └── results/          # Benchmark output — gitignored, never commit
├── scripts/              # Dev/ops helpers (setup, run benchmarks, deploy, serve model)
├── infra/                # Server configs: vLLM serve scripts, OpenClaw config, systemd units
├── docs/                 # Design notes, benchmark methodology, reports
├── pyproject.toml        # uv workspace root (members: apps/*, packages/*)
├── uv.lock               # Single lockfile for the whole repo — commit it
├── .env.example          # All required env vars, no real values
├── AGENTS.md
└── CLAUDE.md
```

Rules:

- New runnable thing → `apps/<name>/`. Code used by more than one app → `packages/<name>/`.
- Apps may depend on packages; packages must not depend on apps.
- One-off scripts go in `scripts/`. If a script grows real logic, move it into a package
  and keep a thin wrapper in `scripts/`.
- Package names use `snake_case` for the import name and `kebab-case` for the
  distribution name (`openclaw-bench` → `import openclaw_bench`).

## Tooling

- **Python** ≥ 3.12, managed with **uv** (workspace mode). Do not use pip, poetry or conda.
- **ruff** for lint + format, **pytest** for tests.
- **Git LFS** for binary test files (`*.pdf`, `*.docx`, `*.pptx`, `*.xlsx`, images).
  Run `git lfs install` once per machine.

Common commands (run from repo root):

```bash
uv sync --all-packages                 # install everything
uv run ruff check . --fix              # lint
uv run ruff format .                   # format
uv run pytest                          # all tests
uv run --package <name> pytest         # tests of one app/package
uv add --package <name> <dependency>   # add a dependency to one member
```

Never edit `uv.lock` by hand.

## Benchmarks

- Every suite reads its config (model, endpoint, dataset, repetitions) from a file or CLI
  args — no hard-coded endpoints or model names.
- Results are written as JSON/JSONL to `benchmarks/results/<suite>/<timestamp>/` and
  must include: git commit, model name, server/runtime version (e.g. vLLM), relevant
  server flags (quantization, context length), dataset name and hardware host.
- Performance runs: do a warm-up request first, report median and p95 over several runs,
  separate prefill from decode. Note that other users on the GPU host skew numbers.
- Quality/extraction runs: use `temperature=0` and a fixed seed where supported; keep the
  scoring method deterministic and documented in the suite's README.
- Adding a dataset: put inputs in `inputs/`, ground truth in `expected/` with the same
  base name, and write a `README.md` with source and license. Only add documents we are
  allowed to redistribute — no personal data, no copyrighted course material.
- Keep datasets small. If a file is > 50 MB, discuss it first.

## Infrastructure

- **LLM server**: vLLM on the HTWG GPU host (SSH alias `gpu-htwg`), OpenAI-compatible API.
- **OpenClaw host**: separate VM, reached via SSH as the team admin user.
- Endpoints, hosts, model names and keys come from environment variables (see
  `.env.example`), e.g. `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, `OPENCLAW_HOST`.
- Both hosts are only reachable from the HTWG network / VPN.
- The GPU host is shared: don't stop or restart a model server someone else started
  without asking in the team chat. Long downloads/servers run detached (systemd/tmux),
  not tied to an SSH session.
- Server-side scripts and units live in `infra/` so the setup is reproducible —
  if you change something on a server, mirror it there.

## Secrets & privacy

- Never commit `.env`, tokens, API keys, SSH keys, IP-based credentials or passwords.
  `.env.example` lists variable names only.
- Do not paste secrets into code, tests, benchmark results, logs, issues or PRs.
- The vLLM endpoint has no authentication — don't expose it publicly or post its address.

## Code conventions

- Everything in **English**: code, comments, docstrings, commit messages, PRs, docs.
- Type hints on all public functions; prefer `dataclasses`/`pydantic` over loose dicts.
- Use `httpx` or the `openai` client for LLM calls, wrapped in a shared package —
  don't sprinkle raw HTTP calls across apps.
- Use `logging`, not `print`, outside of CLI output.
- Tests next to the code (`<member>/tests/`). Tests must not require the GPU server;
  mock the LLM client. Tests that hit real services get `@pytest.mark.integration`
  and are skipped by default.

## Git workflow

- Never push directly to `main`. Branch → PR → at least one review.
- Branch names: `feat/…`, `fix/…`, `bench/…`, `docs/…`, `chore/…`.
- Commits follow **Conventional Commits**, optionally with scope = app/package:
  `feat(bench): add pdf extraction suite`.
- Keep PRs focused. Before opening one: `ruff check`, `ruff format`, `pytest` must pass.
- Benchmark result reports belong in `docs/` (summarized), not raw result files.

## For agents

- Read this file and the README of the app/package you touch before changing code.
- Prefer small, reviewable changes; don't reformat unrelated files.
- Don't run benchmarks or SSH into team servers unless explicitly asked — they cost
  shared GPU time.
- Don't add new top-level directories or new tools (task runners, frameworks) without
  being asked; propose it instead.
- If something in this file is outdated, say so and suggest the fix.
