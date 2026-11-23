# GPU server (`<gpu-host>`)

Reference for the shared HTWG GPU host. Addresses and credentials are intentionally
not listed here (public repo) — see the team chat / `.env`. Reach it with `ssh <gpu-host>`
from the HTWG network or VPN.

## Hardware

| | |
|---|---|
| CPU | AMD Ryzen AI MAX+ PRO 395, 32 cores |
| GPU | Radeon 8060S, integrated APU, **gfx1151** (RDNA 3.5) |
| OS | Ubuntu 24.04 LTS |
| Disk | 1.9 TB |

### Memory split (BIOS UMA setting)

| | GPU | Host RAM |
|---|---|---|
| before | ~47 GB | ~62 GB |
| **now** | **96 GiB** | **31 GB** (~12–29 GB available) |

**Host RAM is now the scarce resource, not VRAM.** It gates loading a second model in
Ollama and limits Docker builds and the RAG service.

## ROCm

The system ROCm is **6.3.3, too old for gfx1151**: a llama.cpp build against it fails
with `ROCm error: out of memory` regardless of model or flags. Build and run inside the
container `rocm/dev-ubuntu-24.04:7.2.4-complete`, or use a prebuilt that bundles its own
ROCm (see [inkling-2-mini.md](inkling-2-mini.md)).

Containers need `--device /dev/kfd --device /dev/dri` and the **numeric** group IDs
(`--group-add 992 --group-add 44`; the image has no `render` group by name).

## Services

| Service | Port | Notes |
|---|---|---|
| llama-server (Inkling 2 Mini) | 8080 | native process, `infra/llama-server/inkling-serve.sh` |
| llama-server (Qwen3.8-27B + MTP) | 8080 | alternative, container `llama-mtp`, stopped — same port |
| LiteLLM proxy | 8081 | routes any model name to `:8080`, merges system messages |
| Ollama | 11434 | stopped, doesn't fit next to llama-server in host RAM |
| RAG service | 9110 | multilingual-e5-large embeddings |
| PII filter (GLiNER2, CPU) | 9111 | `/redact`, `/extract` |
| Pseudonymization proxy | 9112 | see [pseudonymization-proxy.md](pseudonymization-proxy.md) |

`restart: unless-stopped` does **not** survive a manual `docker stop`: a container stopped
by hand stays down after a reboot. For "backend dead" symptoms check `docker ps -a` first,
not the logs.

## Ollama pitfalls (when it is used)

1. **Do not set `HSA_OVERRIDE_GFX_VERSION`.** Forcing gfx1030 on a gfx1151 APU finds no
   device and silently falls back to CPU (`library=cpu`, `total_vram="0 B"` in the log).
2. **No `curl` in the image** — use `healthcheck: ["CMD","ollama","list"]`.
3. **Ollama reads `MemFree`, not `MemAvailable`.** After reading a large model file the page
   cache fills host RAM, and a second model is refused (`system_limited=true`) even with
   tens of GiB of VRAM free. An eviction also drops the prefix cache.

## Tuning rules for this APU

- **No hybrid CPU/GPU offload.** VRAM is the same physical RAM, so CPU layers save nothing
  and are 10–20× slower. Offload all layers and spend the remaining memory on context.
- **Bandwidth is the limit, so MoE beats dense.** A dense 27B reads all weights per token
  (~12 tok/s); a 30B MoE with ~3B active reads a fraction (~45 tok/s). "Active parameters"
  are a lower bound on bytes read per token, not a prediction (hybrid Mamba/attention
  layers are read in full).
- KV cache: `q8_0` for both K and V (smaller **and** faster). Mixed K/V types cost 51–65 %
  prefill on ROCm.
- Flash attention on. Default `-b 2048 -ub 512` is already optimal.

## Measured throughput (single stream)

| Model | Setup | Generation |
|---|---|---|
| Qwen3.6 30B MoE | Ollama | 45 tok/s |
| gemma4 | Ollama | 50 tok/s |
| Qwen3.8-27B dense Q4 | Ollama / llama.cpp | 11.8 tok/s |
| Qwen3.8-27B Q4 + MTP | llama-server | 28–34 tok/s |
| Nemotron-3-Super-120B (A12B) IQ4_XS | Ollama | 22 tok/s |
| Inkling 2 Mini Q4_K_XL | llama-server | 22.7 tok/s (24.6–31 with DSpark on code/math) |

Prefix caching works (a 2.5k-token prefix: 7 s → 0.15 s), but a cold agent prompt of
20k tokens costs 70–80 s of prefill. Anything that evicts the slot (another request, a
subagent) makes the next turn pay that again.

## Download speed

The uplink is 1 Gbit/s since 2026-09-08 (~105 MB/s with 4 parallel connections). When
measuring, use `curl -L` — without it you time the 302 redirect.
