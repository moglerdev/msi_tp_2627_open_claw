#!/usr/bin/env python3
"""
RAG service for the Hermes Mattermost bot.

Runs on the GPU box. Parses documents with Docling, embeds chunks
with multilingual-e5-large, stores them channel-scoped in a persistent ChromaDB,
and answers retrieval queries.

Exposes a tiny HTTP API consumed by the docling-rag MCP tool on the bot server:
  POST /ingest   {file_b64, filename, channel_id, [doc_id], [meta]}  -> chunk count
  POST /query    {query, channel_id, [top_k]}                         -> matching chunks
  GET  /health
  GET  /stats    [?channel_id=...]

Persistent across reboots via an @reboot crontab entry (no sudo/linger on this box).
"""
import base64
import os
import tempfile
import threading
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
from docling.document_converter import DocumentConverter
from docling.chunking import HybridChunker

DATA_DIR = os.path.expanduser("~/rag-data")
CHROMA_DIR = os.path.join(DATA_DIR, "chroma")
EMBED_MODEL = "intfloat/multilingual-e5-large"
PORT = int(os.environ.get("RAG_PORT", "9110"))

os.makedirs(CHROMA_DIR, exist_ok=True)

# --- heavy singletons, loaded once ---
print("Loading embedding model:", EMBED_MODEL, flush=True)
_embedder = SentenceTransformer(EMBED_MODEL)
_converter = DocumentConverter()
_chunker = HybridChunker()
_chroma = chromadb.PersistentClient(
    path=CHROMA_DIR, settings=Settings(anonymized_telemetry=False)
)
# one Chroma collection per Mattermost channel keeps retrieval channel-scoped.
_collection_lock = threading.Lock()


def _collection(channel_id: str):
    # collection names must be 3-512 chars, [a-zA-Z0-9._-]; channel ids already fit.
    name = f"ch_{channel_id}"
    with _collection_lock:
        return _chroma.get_or_create_collection(
            name=name, metadata={"hnsw:space": "cosine"}
        )


def _embed_passages(texts):
    # e5 expects a "passage: " / "query: " prefix on inputs.
    return _embedder.encode(
        [f"passage: {t}" for t in texts], normalize_embeddings=True
    ).tolist()


def _embed_query(text):
    return _embedder.encode(
        [f"query: {text}"], normalize_embeddings=True
    ).tolist()[0]


app = FastAPI(title="docling-rag")


class IngestReq(BaseModel):
    file_b64: str
    filename: str
    channel_id: str
    doc_id: str | None = None
    meta: dict | None = None


class QueryReq(BaseModel):
    query: str
    channel_id: str
    top_k: int = 5


@app.get("/health")
def health():
    return {"ok": True, "embed_model": EMBED_MODEL}


@app.post("/ingest")
def ingest(req: IngestReq):
    try:
        raw = base64.b64decode(req.file_b64)
    except Exception as e:
        raise HTTPException(400, f"bad base64: {e}")

    doc_id = req.doc_id or str(uuid.uuid4())
    suffix = os.path.splitext(req.filename)[1] or ".bin"

    # Docling reads from a path; write the upload to a temp file first.
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as fh:
        fh.write(raw)
        tmp_path = fh.name
    try:
        result = _converter.convert(tmp_path)
        chunks = [c.text for c in _chunker.chunk(result.document) if c.text.strip()]
    except Exception as e:
        raise HTTPException(422, f"docling could not parse {req.filename}: {e}")
    finally:
        os.unlink(tmp_path)

    if not chunks:
        return {"doc_id": doc_id, "chunks": 0, "note": "no extractable text"}

    embeddings = _embed_passages(chunks)
    base_meta = {"filename": req.filename, "doc_id": doc_id}
    if req.meta:
        base_meta.update({k: str(v) for k, v in req.meta.items()})
    metadatas = [{**base_meta, "chunk": i} for i in range(len(chunks))]
    ids = [f"{doc_id}:{i}" for i in range(len(chunks))]

    _collection(req.channel_id).add(
        ids=ids, documents=chunks, embeddings=embeddings, metadatas=metadatas
    )
    return {"doc_id": doc_id, "filename": req.filename, "chunks": len(chunks)}


@app.post("/query")
def query(req: QueryReq):
    col = _collection(req.channel_id)
    if col.count() == 0:
        return {"matches": [], "note": "no documents ingested in this channel yet"}
    res = col.query(
        query_embeddings=[_embed_query(req.query)],
        n_results=min(req.top_k, col.count()),
    )
    matches = []
    for doc, meta, dist in zip(
        res["documents"][0], res["metadatas"][0], res["distances"][0]
    ):
        matches.append(
            {
                "text": doc,
                "filename": meta.get("filename"),
                "doc_id": meta.get("doc_id"),
                "score": round(1.0 - dist, 4),  # cosine distance -> similarity
            }
        )
    return {"matches": matches}


@app.get("/stats")
def stats(channel_id: str | None = None):
    if channel_id:
        return {"channel_id": channel_id, "chunks": _collection(channel_id).count()}
    cols = _chroma.list_collections()
    return {"channels": {c.name: c.count() for c in cols}}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
