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

## Docs

- [GPU server](docs/gpu-server.md) — hardware, memory split, services, tuning rules
- [llama.cpp on gfx1151](docs/llama-cpp-on-gfx1151.md) — benchmarks, MTP, KV cache, ROCm pitfalls
- [Inkling 2 Mini](docs/inkling-2-mini.md) — setup, DSpark drafter, measurements
- [Hermes deployment notes](docs/hermes-profiles.md) — profiles, model wiring, pitfalls
- [Pseudonymization proxy](docs/pseudonymization-proxy.md) — keeping PII away from external LLMs
- [llama-server start scripts](infra/llama-server/README.md)
- [Pseudonymization proxy source](apps/pseudonymization-proxy/), [RAG service](apps/rag-service/SETUP.md), [benchmark](benchmarks/pseudonymization/README.md)

Conventions for humans and AI agents: [AGENTS.md](AGENTS.md).
