# Docling RAG for Hermes personas

RAG pipeline for documents uploaded via Mattermost. Parsing with Docling,
embeddings with `multilingual-e5-large`, vector store ChromaDB (separated per channel).

> The bot server used to run "OpenClaw" and has since migrated to **Hermes Agent**
> (multi-profile). Everything below describes the current Hermes setup.

## Architecture

```
Mattermost upload
  -> Hermes profile (e.g. "gauss")
      -> MCP docling-rag (mcp.py in this directory)
          - ingest_uploaded_document(file_id|url, channel_id)
          - search_uploaded_documents(query, channel_id)
          (downloads the Mattermost file with the bot token from
           MATTERMOST_TOKEN/MATTERMOST_URL, which the Hermes profile passes in
           the env: block of mcp_servers.docling-rag, so each persona
           automatically uses its own bot token)
  -> RAG service (GPU host, http://<gpu-host>:9110, service.py)
      - Docling parse + HybridChunker
      - e5-large embeddings (CPU)
      - ChromaDB persistent in ~/rag-data/chroma, one collection per channel
```

## GPU host

- venv: `~/rag-env` (docling, sentence-transformers, chromadb, fastapi, torch+cpu)
- Service: `service.py`, launcher `start.sh` (port 9110, `HF_HOME=~/rag-data/hf`)
- Data: `~/rag-data/chroma` (vector store), `~/rag-data/hf` (model cache)
- Log: `~/rag-service.log`
- Start: `bash ~/rag-start.sh`, health: `curl localhost:9110/health`
- HTTP API: `POST /ingest`, `POST /query`, `GET /health`, `GET /stats`
- Autostart via cron: `@reboot /usr/bin/env bash $HOME/rag-start.sh`
  (the launcher works offline, see the comments in `start.sh`)

## Bot server

- MCP script: `mcp.py`, shared by every Hermes profile that registers it in its
  `config.yaml` under `mcp_servers.docling-rag`. Mattermost token and URL come from
  the profile's own `.env` through the `env:` block (no secret in the script).
- Set `RAG_BASE_URL` to the service address (default `http://127.0.0.1:9110`).
- Currently wired into one persona profile only; the default profile has no RAG access.
- **Fixed bug:** the tool names in `TOOLS` did not match the keys in `HANDLERS`, so
  every `tools/call` failed with `Unknown tool`. Verified end to end with
  `tools/list` + `tools/call` against a running RAG service.

## Verified

- RAG service reachable after a restart (`{"ok":true}`, e5-large loaded).
- MCP `initialize` / `tools/list` / `tools/call` run end to end against the real service.
- **Still to test live:** whether the model calls the tools with a correct `file_id`
  AND `channel_id` once real uploads arrive via Mattermost. If the `channel_id` is not
  passed reliably, inject it server-side.
