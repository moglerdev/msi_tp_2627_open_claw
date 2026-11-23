#!/usr/bin/env bash
# Launcher for the Docling-RAG service. Kills any process bound to the RAG port,
# then starts the service detached with a writable HF cache.
set -u
PORT=9110
export HF_HOME="$HOME/rag-data/hf"
mkdir -p "$HF_HOME"

# free the port if something is already listening
fuser -k "${PORT}/tcp" 2>/dev/null || true
sleep 1

setsid "$HOME/rag-env/bin/python" "$HOME/rag-service.py" \
    > "$HOME/rag-service.log" 2>&1 < /dev/null &
disown
echo "launched pid $!"
