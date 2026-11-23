# llama-server start scripts

Two ways to serve the shared GPU server's model on port 8080. **Only one can run at a
time** (same port, and both together don't fit in host RAM). Tell the team before switching.

| Script | Model | Speculative decoding | Single-stream speed |
|---|---|---|---|
| `inkling-serve.sh` | Inkling 2 Mini Q4_K_XL | DSpark drafter | ~23 tok/s (24–31 on code/math) |
| `qwen-mtp-serve.sh` | Qwen3.8-27B Q4_K_XL | MTP head | 28–34 tok/s |

Background: [`docs/gpu-server.md`](../../docs/gpu-server.md),
[`docs/inkling-2-mini.md`](../../docs/inkling-2-mini.md).

> **Status:** both scripts were reconstructed from the documented flags while the server
> was unreachable. They have not been diffed against the originals on the server
> (`~/inkling/iserve.sh`, `~/lserve.sh`). Check before treating them as the source of truth.

Common to both: all layers on the GPU (`-ngl 99`), flash attention, `q8_0` for both K and V
(mixing types costs 51–65 % prefill on ROCm), `--jinja` (needed for tool calling),
`--mmproj` (without it the model can't see images), one slot (`--parallel 1`).

Switching:

```bash
pkill -x llama-server; ./inkling-serve.sh      # Qwen -> Inkling (if Qwen runs natively)
docker rm -f llama-mtp; ./inkling-serve.sh     # Qwen container -> Inkling
pkill -x llama-server; ./qwen-mtp-serve.sh     # Inkling -> Qwen
```
