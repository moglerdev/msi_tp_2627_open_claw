#!/usr/bin/env python3
"""Minimal MCP server (stdio) for Docling RAG.

Two tools, usable by any Hermes persona that mounts this MCP server:
  - ingest_document : downloads a file uploaded to Mattermost (by file_id OR
                      full URL), sends it to the RAG service on the GPU box,
                      which parses it with Docling, chunks it and stores it
                      channel-scoped in ChromaDB.
  - search_documents: searches the documents stored for THIS channel and
                      returns the most relevant passages for answering.

Mattermost token/base URL come as env vars (MATTERMOST_TOKEN, MATTERMOST_URL)
from the Hermes profile that starts this MCP server -- so each persona
automatically has its own bot token, no secret in the script itself.
No shell access. Standard library only.
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

RAG_BASE = os.environ.get("RAG_BASE_URL", "http://127.0.0.1:9110")


def _mm_config():
    """Bot token + Mattermost base URL from the environment."""
    token = os.environ.get("MATTERMOST_TOKEN")
    base = os.environ.get("MATTERMOST_URL")
    return token, (base or "").rstrip("/")


def _http(url, data=None, headers=None, method=None, timeout=120):
    req = urllib.request.Request(
        url, data=data, headers=headers or {}, method=method
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), dict(r.headers)


def _download_mattermost_file(ref):
    """ref is a file_id OR a full Mattermost URL. Returns (bytes, filename)."""
    token, base = _mm_config()
    if not token:
        raise RuntimeError("MATTERMOST_TOKEN is not set.")
    ref = ref.strip()
    if ref.startswith("http://") or ref.startswith("https://"):
        url = ref
        # take file_id from .../api/v4/files/<id>[/...], otherwise the last path part
        parts = urllib.parse.urlparse(ref).path.rstrip("/").split("/")
        file_id = parts[parts.index("files") + 1] if "files" in parts else parts[-1]
    else:
        file_id = ref
        url = f"{base}/api/v4/files/{file_id}"
    headers = {"Authorization": f"Bearer {token}"}
    raw, resp_headers = _http(url, headers=headers, timeout=120)
    # filename from Content-Disposition, else Mattermost metadata, else the id
    filename = None
    cd = resp_headers.get("Content-Disposition", "")
    if "filename=" in cd:
        filename = cd.split("filename=")[-1].strip().strip('";')
    if not filename:
        try:
            meta, _ = _http(
                f"{base}/api/v4/files/{file_id}/info", headers=headers, timeout=30
            )
            filename = json.loads(meta).get("name")
        except Exception:
            pass
    return raw, (filename or f"{file_id}.bin")


def ingest_document(a):
    ref = (a.get("file_id") or a.get("url") or "").strip()
    channel_id = (a.get("channel_id") or "").strip()
    if not ref:
        return "ERROR: provide 'file_id' or 'url' of the Mattermost file."
    if not channel_id:
        return "ERROR: 'channel_id' is missing (needed for per-channel storage)."
    try:
        raw, filename = _download_mattermost_file(ref)
    except urllib.error.HTTPError as e:
        return f"ERROR during download (HTTP {e.code}): {e.read().decode()[:200]}"
    except Exception as e:
        return f"ERROR during download: {e}"

    payload = json.dumps(
        {
            "file_b64": base64.b64encode(raw).decode(),
            "filename": filename,
            "channel_id": channel_id,
        }
    ).encode()
    try:
        body, _ = _http(
            f"{RAG_BASE}/ingest",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
            timeout=300,
        )
        res = json.loads(body)
    except urllib.error.HTTPError as e:
        return f"ERROR during processing (HTTP {e.code}): {e.read().decode()[:300]}"
    except Exception as e:
        return f"ERROR during processing: {e}"

    n = res.get("chunks", 0)
    if n == 0:
        return f"'{filename}' contained no extractable text ({res.get('note','')})."
    return (
        f"Document '{filename}' processed: {n} sections indexed and searchable "
        f"in this channel. (doc_id={res.get('doc_id')})"
    )


def search_documents(a):
    query = (a.get("query") or "").strip()
    channel_id = (a.get("channel_id") or "").strip()
    top_k = a.get("top_k") or 5
    if not query:
        return "ERROR: 'query' is missing."
    if not channel_id:
        return "ERROR: 'channel_id' is missing."
    try:
        top_k = max(1, min(10, int(top_k)))
    except Exception:
        top_k = 5
    payload = json.dumps(
        {"query": query, "channel_id": channel_id, "top_k": top_k}
    ).encode()
    try:
        body, _ = _http(
            f"{RAG_BASE}/query",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
            timeout=60,
        )
        res = json.loads(body)
    except Exception as e:
        return f"ERROR during search: {e}"

    matches = res.get("matches", [])
    if not matches:
        return res.get("note", "Keine passenden Dokumente in diesem Channel gefunden.")
    out = [f"{len(matches)} relevante Textstellen:"]
    for i, m in enumerate(matches, 1):
        out.append(
            f"\n[{i}] aus '{m.get('filename')}' (Relevanz {m.get('score')}):\n{m.get('text')}"
        )
    return "\n".join(out)


TOOLS = [
    {
        "name": "ingest_uploaded_document",
        "description": (
            "Process a document uploaded to Mattermost (PDF, DOCX, PPTX, "
            "XLSX, image) for later search. Use this as soon as someone sends a file "
            "whose content should be used. Pass the attachment's file_id (or "
            "URL) AND the current channel's channel_id."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "Mattermost file_id of the attachment"},
                "url": {"type": "string", "description": "Alternatively: full URL of the file"},
                "channel_id": {"type": "string", "description": "ID of the current Mattermost channel"},
            },
            "required": ["channel_id"],
        },
    },
    {
        "name": "search_uploaded_documents",
        "description": (
            "Search the files/documents uploaded via chat in THIS channel "
            "for relevant passages to answer a question. NOT for the "
            "Outline knowledge base (use `search_documents` for that), only for files "
            "someone uploaded directly into the chat. Use this for questions that refer "
            "to previously shared files/documents. Returns the best-matching "
            "sections; compose the answer from them."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search question / topic"},
                "channel_id": {"type": "string", "description": "ID of the current Mattermost channel"},
                "top_k": {"type": "integer", "description": "Number of passages (1-10, default 5)"},
            },
            "required": ["query", "channel_id"],
        },
    },
]

HANDLERS = {
    "ingest_uploaded_document": ingest_document,
    "search_uploaded_documents": search_documents,
}


def reply(i, result=None, error=None):
    m = {"jsonrpc": "2.0", "id": i}
    if error is not None:
        m["error"] = error
    else:
        m["result"] = result
    sys.stdout.write(json.dumps(m) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except Exception:
        continue
    method = msg.get("method")
    mid = msg.get("id")
    if method == "initialize":
        reply(
            mid,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "docling-rag", "version": "1.0.0"},
            },
        )
    elif method == "tools/list":
        reply(mid, {"tools": TOOLS})
    elif method == "tools/call":
        pr = msg.get("params", {})
        fn = HANDLERS.get(pr.get("name"))
        if fn:
            reply(mid, {"content": [{"type": "text", "text": fn(pr.get("arguments", {}))}]})
        else:
            reply(mid, error={"code": -32601, "message": "Unknown tool"})
    elif mid is not None:
        reply(mid, error={"code": -32601, "message": "Unknown method"})
