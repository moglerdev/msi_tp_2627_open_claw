# Hermes — MSI Team Project WS 2026/27

Running the Hermes agent against a self-hosted LLM (vLLM) and benchmarking
performance, answer quality and document extraction.

## Setup

```bash
git lfs install
uv sync --all-packages
cp .env.example .env   # fill in values
```

## Layout

- `apps/` — runnable applications
- `packages/` — shared libraries
- `benchmarks/` — suites, datasets (txt, pdf, …) and results
- `scripts/` — dev/ops helpers
- `infra/` — server configs (vLLM, Hermes, systemd)
- `docs/` — notes and reports

Conventions for humans and AI agents: [AGENTS.md](AGENTS.md).
