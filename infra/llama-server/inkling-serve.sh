#!/usr/bin/env bash
# Start llama-server with Inkling 2 Mini (Q4_K_XL) + DSpark drafter + vision.
#
# NOTE: reconstructed from the documented flags, not copied byte-for-byte from the
# server's ~/inkling/iserve.sh. Diff against the original before relying on it.
#
# Usage: inkling-serve.sh [draft-n-max=3] [ctx=131072]
# Layout expected in $INKLING_DIR (default ~/inkling):
#   bin/                                  Unsloth llama.cpp prebuilt (rocm-gfx1151, b12588-mix-c0c3de8)
#   Inkling-2-Mini-UD-Q4_K_XL.gguf        root GGUF, NOT Mainline_Support/
#   dspark-Q8_0.gguf                      DSpark block drafter
#   mmproj-F16.gguf                       vision projector
set -euo pipefail

DIR="${INKLING_DIR:-$HOME/inkling}"
DMAX="${1:-3}"
CTX="${2:-131072}"

cd "$DIR/bin"
# the prebuilt bundles its own ROCm libraries next to the binary
export LD_LIBRARY_PATH="$PWD${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

exec ./llama-server \
  -m "$DIR/Inkling-2-Mini-UD-Q4_K_XL.gguf" \
  --mmproj "$DIR/mmproj-F16.gguf" \
  -md "$DIR/dspark-Q8_0.gguf" --spec-type draft-dspark --spec-draft-n-max "$DMAX" -ngld 99 \
  -ngl 99 -fa 1 -ctk q8_0 -ctv q8_0 \
  -c "$CTX" --parallel 1 \
  --temp 1.0 --top-p 1.0 --top-k 0 --min-p 0 \
  --jinja --alias inkling-2-mini \
  --host 0.0.0.0 --port 8080
