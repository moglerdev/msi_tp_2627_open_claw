#!/usr/bin/env bash
# Start llama-server with Qwen3.8-27B (Q4_K_XL) + MTP speculative decoding + vision,
# in a ROCm 7.2 container (the host's ROCm 6.3.3 is too old for gfx1151).
#
# NOTE: reconstructed from the documented flags, not copied byte-for-byte from the
# server's ~/lserve.sh. The llama.cpp build path below is an assumption.
#
# Usage: qwen-mtp-serve.sh [draft-n-max=5] [ctx=131072]
# Expects: $SRC (llama.cpp build with HIP, gfx1151) and $MODELS containing
#   qwen27b-Q4_K_XL.gguf, mtp-27b-Q4_0.gguf, mmproj-F16.gguf
set -euo pipefail

DMAX="${1:-5}"
CTX="${2:-131072}"
SRC="${LLAMA_SRC:-$HOME/src/llama.cpp}"
MODELS="${MODELS_DIR:-$HOME/gguf}"

docker rm -f llama-mtp >/dev/null 2>&1 || true
# --group-add needs numeric GIDs (render=992, video=44); the image has no named groups.
exec docker run -d --name llama-mtp \
  --device /dev/kfd --device /dev/dri --group-add 992 --group-add 44 \
  --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -p 8080:8080 -v "$SRC:/src" -v "$MODELS:/models:ro" -w /src \
  rocm/dev-ubuntu-24.04:7.2.4-complete \
  ./build/bin/llama-server \
    -m /models/qwen27b-Q4_K_XL.gguf \
    -md /models/mtp-27b-Q4_0.gguf -ngld 99 --spec-draft-n-max "$DMAX" \
    --mmproj /models/mmproj-F16.gguf \
    -ngl 99 -fa 1 -ctk q8_0 -ctv q8_0 -c "$CTX" --parallel 1 --cache-reuse 256 \
    --jinja --alias qwen3.8-27b-mtp --host 0.0.0.0 --port 8080
