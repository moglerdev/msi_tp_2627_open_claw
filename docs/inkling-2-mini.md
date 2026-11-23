# Inkling 2 Mini on the GPU server

[Inkling 2 Mini](https://thinkingmachines.ai/news/inkling-2-mini/) (Thinking Machines Lab,
2026-11-20, Apache 2.0): 26B-parameter MoE, 3.4B active, **looped transformer** (the middle
12 of 24 layers run three times per token, so ~5.4B effective active parameters).
Natively trained in NVFP4 (last four layers MXFP8), ~20 GB. Multimodal (text + images).

## Setup that runs

| | |
|---|---|
| Quant | `UD-Q4_K_XL` (Unsloth), 16.4 GiB, mean KLD 0.0107 vs Q8, 98 % same top token |
| Runtime | Unsloth llama.cpp prebuilt `b12588-mix-c0c3de8`, asset `…linux-x64-rocm-gfx1151` |
| Speculative decoding | DSpark block drafter (`dspark-Inkling-2-Mini-Q8_0.gguf`), `--spec-draft-n-max 3` |
| Vision | `mmproj-F16.gguf` |
| Context | 131072, KV cache `q8_0` |

The prebuilt carries its own ROCm 7.18, so no container build is needed. Start with
[`infra/llama-server/inkling-serve.sh`](../infra/llama-server/inkling-serve.sh).

### Why not the usual route

- **Not MTP.** The model ships a DSpark drafter, not an MTP head. Use
  `--spec-type draft-dspark`, not `--mtp`.
- **Mainline llama.cpp is not enough.** It needs ggml-org/llama.cpp PR 32704, otherwise the
  output is gibberish (perplexity ~130 instead of 7.65), and it doesn't know DSpark. Use
  the Unsloth prebuilt with the **root** GGUFs (not the `Mainline_Support/` ones).
- **Why Q4 and not NVFP4.** gfx1151 has no native FP4 kernels; Q4_K_XL is the best
  size/quality point for a bandwidth-bound APU (Q8_K_XL is 21 GiB and slower).
- The prebuilt is third-party code from a fork — checksum it against
  `llama-prebuilt-sha256.json` from the release before use.

Sampling from the model card: `temp 1.0, top-p 1.0, top-k 0, min-p 0`.

## Measurements (2026-11-23, 600 tokens, thinking off, one slot)

| Prompt | no drafter | DSpark, n-max 3 | acceptance |
|---|---|---|---|
| code | 22.8 tok/s | **24.6** | 43 % |
| prose | 22.7 | **14.5** | 11 % |
| math | 22.7 | **31.2** | 64 % |
| JSON | 22.7 | **25.2** | 46 % |

n-max 2 was not better. The drafter pays off on predictable text (math +37 %,
code/JSON +8–11 %) and costs a third on free prose. For agent and coding work keep it at 3.

Overall that is **slower than Qwen3.8-27B + MTP** (28–34 tok/s); the claimed advantage is
agentic benchmark quality, which we have not measured ourselves.

Prefill is 75–157 tok/s on short prompts and ~270 tok/s on long ones. A Hermes prompt of
18k tokens takes 67 s cold.

## Verified

- Tool calling: `get_weather {"city":"…"}` parsed correctly, `finish_reason: tool_calls`,
  follow-up turn with the tool result answered correctly.
- Vision: a generated test image (circle, rectangle, triangle, text) was described correctly
  with the drafter and mmproj active.

**Not tested:** parallel requests (one slot), long agent runs, Claude Code through the
LiteLLM proxy (its system-message merge hook was written for Qwen's chat template).

## Switching back to Qwen

```bash
ssh <gpu-host> 'pkill -x llama-server; ~/lserve.sh'    # Qwen3.8-27B + MTP, see infra/llama-server/
```

Both use port 8080; the GPU host is shared, so tell the team before switching.
