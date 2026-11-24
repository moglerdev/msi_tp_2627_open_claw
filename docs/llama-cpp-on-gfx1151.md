# llama.cpp on gfx1151 (measured 2026-09-08)

`llama-bench`, Qwen3.8-27B Q4_K_XL / Q3_K_XL, `-ngl 99 -fa 1 -ctk q8_0 -ctv q8_0`.

## Ollama has no measurable overhead

| | Ollama | llama.cpp (ROCm 7.2) |
|---|---|---|
| Q4 generation | 11.8 tok/s | 11.85 |
| Q3 generation | 14.7 tok/s | 14.66 |

Ollama *is* llama.cpp. Q4 runs at ~85 % of the theoretical 256 GB/s, so no runtime can
unlock more. The only reason to run llama-server directly is features Ollama lacks
(MTP/DSpark speculative decoding).

## ROCm vs Vulkan

Prefill favours ROCm by 5–11 % (compute bound), generation favours Vulkan by 1–3 %
(bandwidth bound). Both marginal; no reason to switch.

## Batch size

`-b 2048 -ub 512` (default) is optimal. Larger `-ub` (1024, 2048) lowers prefill.

## KV cache types

Q4, pp2048/tg128 on ROCm:

| K / V | prefill | generation |
|---|---|---|
| q8_0 / q8_0 | **379** | **11.84** |
| f16 / f16 | 337 | 9.9 (noisy) |
| f16 / q8_0 | 133 | 11.5 |
| q8_0 / f16 | 185 | 11.5 |

Mixed K/V types fall off the fused path on ROCm and lose 51–65 % prefill. Use equal types.

## System ROCm 6.3.3 is too old

A llama.cpp built against `/opt/rocm` (6.3.3) fails with `ROCm error: out of memory` in
`ggml_backend_cuda_set_tensor_async` for every layer count, model and flag combination.
It is not host RAM. Building inside `rocm/dev-ubuntu-24.04:7.2.4-complete` works at once.

## Speculative decoding with MTP (Qwen3.8-27B)

Qwen3.8-27B ships an MTP head, available as a 1.37 GB sidecar. Q4_K_XL, 400 tokens, temp 0:

| Prompt | baseline | MTP | factor |
|---|---|---|---|
| code | 11.8 | 28.1 | 2.38× |
| prose | 11.8 | 21.6 | 1.83× |
| math | 11.8 | 34.0 | 2.88× |
| JSON | 11.8 | 30.7 | 2.60× |

- `--spec-draft-n-max`: optimum **5** (default 3 loses ~15 %; beyond 6 it drops sharply).
- Q4+MTP beats pure Q3 by 92 %; Q3+MTP is slower than Q4+MTP (lower draft acceptance).
- n-gram self-speculation gives nothing.
- Thinking mode halves draft acceptance (41 % vs 65 %); turn it off when throughput matters
  (`--reasoning off` or `chat_template_kwargs: {"enable_thinking": false}`).
- Outputs are almost always bit-identical to the baseline; the rare differences come from
  floating-point reduction order in batched verification, not from an algorithm error.

## Vision

The vision projector is a separate file (`mmproj-F16.gguf`, 885 MB). Ollama pulled it in
silently; llama-server needs `--mmproj`. MTP and vision work together, but
`--cache-reuse` is disabled with multimodal (normal prefix reuse still works).

## Tool calling

`--jinja` is required so the model's embedded chat template (which knows tools) is used.
