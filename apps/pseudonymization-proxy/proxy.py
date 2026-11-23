#!/usr/bin/env python3
"""Reversible pseudonymizing OpenAI-compatible proxy.

Client (Hermes, opencode, pi) -> :9112 -> upstream (OpenRouter or similar)

Before forwarding, personal data in all messages is replaced by placeholders
("Julia Hartmann" -> "[PERSON_1]"); in the answer the placeholders are mapped back
to the originals, also when streaming and inside tool-call arguments. The upstream
never sees the original values.

Detection: GLiNER2 service on :9111 (/extract) plus regexes for structured data
(mail, IBAN, phone, IP, credit card). Results are cached per message by hash so the
history that is re-sent on every turn does not have to be detected again.

The mapping lives in memory only for the duration of one request and is never
logged. Numbering is deterministic (order of first occurrence) so the same history
gets the same placeholders on every turn -> the upstream's prefix cache stays valid.

Standard library only.

Env:
  PSEUDO_PORT        port (9112)
  PSEUDO_UPSTREAM    upstream base URL (https://openrouter.ai/api/v1)
  PSEUDO_PII_URL     PII service (http://127.0.0.1:9111)
  PSEUDO_ROLES       roles that are pseudonymized (user,assistant,tool)
                     -- "system" is off by default: bot config, large, rarely
                     changes; add "system" if needed
  PSEUDO_THRESHOLD   GLiNER threshold (0.5)
  PSEUDO_FAIL_OPEN   1 = forward unfiltered when the PII service is down.
                     Default 0: nothing is sent, the client gets a notice text
                     as the answer (HTTP 200, see FALLBACK_MODELS).
  PSEUDO_FALLBACK_MODELS  comma list, tried by the proxy itself on 401/403/404/429/5xx
  PSEUDO_AUDIT       1 = write audit log (default), 0 = off
  PSEUDO_AUDIT_DIR   ~/pseudo-audit
  PSEUDO_AUDIT_DAYS  retention in days (30)
  PSEUDO_DEBUG_ALLOW client IPs allowed for /debug/* and /ui/ (127.0.0.1,::1), "*" = all.
                     The audit log is sensitive; use "*" only on a host that is
                     reachable from a trusted network (VPN) at all.
  PSEUDO_UI_DIR      built debug UI (~/pseudo-ui, from ui/dist)
  PSEUDO_PDF_CMD     command that reads a PDF on stdin and writes text to stdout
                     ("pdftotext -layout -enc UTF-8 - -")
  PSEUDO_ATTACH_MAX_CHARS  upper limit of text per attachment (90000, PII service: 100k)

Attachments (content part type "file"): PDFs and text files are extracted as text,
pseudonymized and forwarded as type "text" -- the original PDF never leaves. What
cannot be checked (scan without text layer, binary format, URL instead of embedded
data, no PDF tool) is replaced by a notice and NOT sent (fail closed).
"""
import base64
import shlex
import subprocess
import collections
import hashlib
import http.client
import json
import mimetypes
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PSEUDO_PORT", "9112"))
UPSTREAM = os.environ.get("PSEUDO_UPSTREAM", "https://openrouter.ai/api/v1").rstrip("/")
PII_URL = os.environ.get("PSEUDO_PII_URL", "http://127.0.0.1:9111").rstrip("/")
ROLES = set(os.environ.get("PSEUDO_ROLES", "user,assistant,tool").split(","))
THRESHOLD = float(os.environ.get("PSEUDO_THRESHOLD", "0.5"))
FAIL_OPEN = os.environ.get("PSEUDO_FAIL_OPEN", "0") == "1"
# The proxy's own fallback chain. Important: if the proxy returns an error code,
# Hermes switches to its normal fallback chain -- which goes DIRECTLY to
# OpenRouter, i.e. in plain text. So the proxy tries further models itself and
# finally answers with 200 + a notice text instead of an error.
FALLBACK_MODELS = [m for m in os.environ.get("PSEUDO_FALLBACK_MODELS", "").split(",") if m]
# 401/403 too: Hermes switches IMMEDIATELY to its direct chain on those.
# 400 is passed through (not a fallback trigger, Hermes needs it for context compression).
RETRY_STATUS = {401, 402, 403, 404, 408, 429, 500, 502, 503, 504}
PDF_CMD = shlex.split(os.environ.get("PSEUDO_PDF_CMD", "pdftotext -layout -enc UTF-8 - -"))
ATTACH_MAX = int(os.environ.get("PSEUDO_ATTACH_MAX_CHARS", "90000"))

# Hermes only sets the OpenRouter attribution if the base_url contains
# "openrouter.ai" -- behind the proxy it is missing and the free models
# answer 403. The proxy therefore adds missing headers itself.
DEFAULT_HEADERS = {
    "HTTP-Referer": "https://hermes-agent.nousresearch.com",
    "X-Title": "Hermes Agent",
    "X-OpenRouter-Categories": "productivity,cli-agent",
} if "openrouter.ai" in UPSTREAM else {}

# Headers passed through to the upstream. HTTP-Referer is mandatory for
# OpenRouter free models (otherwise 403 "agentic harnesses").
PASS_HEADERS = ("authorization", "http-referer", "x-title", "x-openrouter-categories",
                "x-openrouter-cache", "x-openrouter-cache-ttl", "content-type",
                "accept", "user-agent", "openai-organization", "anthropic-version",
                "x-api-key")


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, file=sys.stderr, flush=True)


# --------------------------------------------------------------- Audit log
#
# Records per request exactly what reached the upstream and what came back --
# pseudonymized, WITHOUT the mapping. Purpose: measure the miss rate (a missed
# name shows up here in plain text) and collect training data.
# Caution: precisely because of the missed values the log itself is sensitive.
# Files 0600, directory 0700, retention PSEUDO_AUDIT_DAYS.
#
#   <dir>/YYYY-MM-DD.jsonl   one request per line
#   <dir>/blobs/<sha256>.txt system prompts and tool definitions, stored once
#                            (otherwise ~100 KB of repetition per Hermes turn)

AUDIT_DIR = os.path.expanduser(os.environ.get("PSEUDO_AUDIT_DIR", "~/pseudo-audit"))
AUDIT_ON = os.environ.get("PSEUDO_AUDIT", "1") == "1"
AUDIT_DAYS = int(os.environ.get("PSEUDO_AUDIT_DAYS", "30"))
_audit_lock = threading.Lock()
_audit_last_prune = [0.0]


def _blob(text):
    h = hashlib.sha256(text.encode()).hexdigest()
    path = os.path.join(AUDIT_DIR, "blobs", h + ".txt")
    if not os.path.exists(path):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(text)
    return "blob:" + h


def _prune():
    if time.time() - _audit_last_prune[0] < 3600:
        return
    _audit_last_prune[0] = time.time()
    cutoff = time.time() - AUDIT_DAYS * 86400
    for sub in ("", "blobs"):
        d = os.path.join(AUDIT_DIR, sub)
        for name in os.listdir(d):
            fp = os.path.join(d, name)
            if os.path.isfile(fp) and os.path.getmtime(fp) < cutoff:
                os.remove(fp)


def audit_write(rec, sent_body):
    if not AUDIT_ON:
        return
    try:
        with _audit_lock:
            os.makedirs(os.path.join(AUDIT_DIR, "blobs"), mode=0o700, exist_ok=True)
            msgs = []
            for m in (sent_body or {}).get("messages", []):
                m = dict(m)
                if m.get("role") == "system" and isinstance(m.get("content"), str) \
                        and len(m["content"]) > 2000:
                    m["content"] = _blob(m["content"])
                msgs.append(m)
            rec["sent_messages"] = msgs
            if (sent_body or {}).get("tools"):
                rec["sent_tools"] = _blob(json.dumps(sent_body["tools"], ensure_ascii=False))
            path = os.path.join(AUDIT_DIR, time.strftime("%Y-%m-%d") + ".jsonl")
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            _prune()
    except Exception as e:  # noqa: BLE001 -- Audit darf nie einen Request kaputt machen
        log(f"audit write failed: {e}")


# --------------------------------------------------------------- Detection

# Telefonnummern: +49 7531 5732123, 07531/57 32-123, (07531) 57 32 123, +49 (0) 171 2345678,
# (+49) 171 ..., 0049 171 ... -- parentheses only if they pair up around the area code.
_PH_START = r"(?<![\w])(?:(?:\(\+\d{1,3}\)|\+\d{1,3}|00\d{1,3})[ \t/-]?(?:\(0\)[ \t/-]?)?(?=\(?\d)|(?=\(?0\d))"
_PH_AREA = r"(?:\(\d{2,5}\)|\d{2,5})"
# Main block: at least 5 digits, groups separated by space/hyphen
_PH_MAIN = r"[ \t/-]?(?=(?:\d[ \t-]?){5,})\d+(?:[ \t-]\d+)*"


class _WrappedPhone:
    """Number split by a line break (PDF column, mail wrapping). Only if the first
    line looks incomplete (<= 9 digits); otherwise this swallows the next line
    ("Tel 07531 5732123\n2026")."""
    rx = re.compile(_PH_START + _PH_AREA + r"[ \t/-]?\d{2,}(?:[ \t-]\d+)*[ \t]*\n[ \t]*\d{2,8}\b")

    def finditer(self, text):
        for m in self.rx.finditer(text):
            if sum(c.isdigit() for c in m.group(0).split("\n")[0]) <= 9:
                yield m


REGEXES = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b")),
    ("CREDIT_CARD", re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b")),
    ("IP_ADDRESS", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("PHONE", re.compile(_PH_START + _PH_AREA + _PH_MAIN + r"\b")),
    ("PHONE", _WrappedPhone()),
]

# Labels GLiNER does find, but whose replacement does more harm than good.
SKIP_LABELS = {"date", "time", "age", "gender", "nationality", "language",
               "religion", "occupation", "job_title"}


# Map GLiNER labels to the same names as the regex categories so a phone
# number is not sometimes PHONE_1 and sometimes PHONE_NUMBER_1.
LABEL_ALIASES = {"PHONE_NUMBER": "PHONE", "EMAIL_ADDRESS": "EMAIL",
                 "CREDIT_CARD_NUMBER": "CREDIT_CARD", "IP": "IP_ADDRESS"}


class LRU:
    def __init__(self, n=4096):
        self.n, self.d, self.lock = n, OrderedDict(), threading.Lock()

    def get(self, k):
        with self.lock:
            if k in self.d:
                self.d.move_to_end(k)
                return self.d[k]
        return None

    def put(self, k, v):
        with self.lock:
            self.d[k] = v
            self.d.move_to_end(k)
            while len(self.d) > self.n:
                self.d.popitem(last=False)


SPAN_CACHE = LRU()


class DetectorDown(Exception):
    pass


def _parse_entities(obj):
    """Tolerates the usual response shapes of /extract."""
    if isinstance(obj, dict):
        for key in ("entities", "spans", "results", "pii"):
            if key in obj:
                return _parse_entities(obj[key])
        return []
    out = []
    for e in obj or []:
        if not isinstance(e, dict):
            continue
        start = e.get("start", e.get("start_char"))
        end = e.get("end", e.get("end_char"))
        label = e.get("label") or e.get("type") or e.get("entity") or "PII"
        score = e.get("score", e.get("confidence", 1.0))
        if start is None or end is None:
            continue
        out.append((int(start), int(end), str(label), float(score)))
    return out


def gliner_spans(text, threshold=None):
    req = urllib.request.Request(
        PII_URL + "/extract",
        data=json.dumps({"text": text, "threshold": THRESHOLD if threshold is None else threshold}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return _parse_entities(json.load(r))
    except Exception as e:  # noqa: BLE001
        raise DetectorDown(str(e)) from e


def detect(text):
    """Returns non-overlapping (start, end, LABEL) spans, sorted."""
    if not text or not text.strip():
        return []
    key = hashlib.sha256(text.encode()).hexdigest()
    hit = SPAN_CACHE.get(key)
    if hit is not None:
        return hit
    spans = []
    for label, rx in REGEXES:
        for m in rx.finditer(text):
            spans.append((m.start(), m.end(), label, 1.0))
    for s, e, label, score in gliner_spans(text):
        if label.lower() in SKIP_LABELS or score < THRESHOLD:
            continue
        spans.append((s, e, label, score))
    # Overlaps: the longer span wins, on a tie the higher confidence
    spans.sort(key=lambda x: (-(x[1] - x[0]), -x[3]))
    taken, result = [], []
    for s, e, label, _ in spans:
        if any(s < te and ts < e for ts, te in taken):
            continue
        frag = text[s:e]
        # Trim edges (punctuation, whitespace)
        ls = len(frag) - len(frag.lstrip(" \t\n.,;:\"'"))
        rs = len(frag) - len(frag.rstrip(" \t\n.,;:\"'"))
        core = frag[ls:len(frag) - rs]
        # Only cut parentheses that are not paired within the span: "(07531) 57 32" keeps
        # the "(", "(0171 1234567)" loses both.
        while core.startswith("(") and ")" not in core:
            core, ls = core[1:], ls + 1
        while core.endswith(")") and "(" not in core:
            core, rs = core[:-1], rs + 1
        while core.startswith(")") or core.endswith("("):
            if core.startswith(")"):
                core, ls = core[1:], ls + 1
            else:
                core, rs = core[:-1], rs + 1
        s, e = s + ls, e - rs
        if e - s < 2:
            continue
        taken.append((s, e))
        norm = re.sub(r"[^A-Z0-9]+", "_", label.upper()).strip("_")
        result.append((s, e, LABEL_ALIASES.get(norm, norm)))
    result.sort()
    SPAN_CACHE.put(key, result)
    return result


# --------------------------------------------------------------- Mapping

PH_RX = re.compile(r"\[?\b([A-Z][A-Z0-9_]*?_\d+)\b\]?")


class Mapping:
    def __init__(self):
        self.fwd = {}   # original -> placeholder
        self.rev = {}   # placeholder key (without brackets) -> original
        self.count = {}

    def placeholder(self, original, label):
        norm = " ".join(original.split())
        if norm in self.fwd:
            return self.fwd[norm]
        n = self.count.get(label, 0) + 1
        self.count[label] = n
        key = f"{label}_{n}"
        self.fwd[norm] = f"[{key}]"
        self.rev[key] = original
        return self.fwd[norm]

    def pseudonymize(self, text):
        spans = detect(text)
        if not spans:
            return text
        out, pos = [], 0
        for s, e, label in spans:
            out.append(text[pos:s])
            out.append(self.placeholder(text[s:e], label))
            pos = e
        out.append(text[pos:])
        return "".join(out)

    def restore(self, text, json_escape=False):
        if not text or not self.rev:
            return text

        def sub(m):
            orig = self.rev.get(m.group(1))
            if orig is None:
                return m.group(0)
            return json.dumps(orig)[1:-1] if json_escape else orig
        return PH_RX.sub(sub, text)


PLACEHOLDER_NOTE = (
    "Data processing note: personal values in this conversation have been replaced "
    "by placeholders such as [PERSON_1], [CITY_1] or [PHONE_1]. Treat every "
    "placeholder as the real value it stands for (name, place, number ...), "
    "answer the request normally and copy placeholders verbatim, including the "
    "square brackets, when you mention the value. The replacement is reversed "
    "automatically afterwards; the user sees the real values.")


def add_placeholder_note(body):
    """Without the note, models take the placeholders for a privacy test
    and refuse (observed live with dots-3-note-preview)."""
    msgs = body.get("messages", [])
    for m in msgs:
        if m.get("role") == "system":
            c = m.get("content")
            if isinstance(c, str):
                m["content"] = c + "\n\n" + PLACEHOLDER_NOTE
                return
            if isinstance(c, list):
                c.append({"type": "text", "text": PLACEHOLDER_NOTE})
                return
    msgs.insert(0, {"role": "system", "content": PLACEHOLDER_NOTE})


# --------------------------------------------------------------- Attachments

TEXT_MIMES = {"application/json", "application/xml", "application/csv",
              "application/x-yaml", "application/yaml", "application/x-ndjson"}


class AttachmentError(Exception):
    pass


def pdf_to_text(raw):
    try:
        r = subprocess.run(PDF_CMD, input=raw, capture_output=True, timeout=60)
    except FileNotFoundError:
        raise AttachmentError(f"no PDF tool ({PDF_CMD[0]}) on the proxy host")
    except subprocess.TimeoutExpired:
        raise AttachmentError("PDF extraction took longer than 60 s")
    if r.returncode != 0:
        raise AttachmentError("PDF not readable (encrypted or damaged?)")
    text = r.stdout.decode("utf-8", "replace").replace("\f", "\n")
    if len(re.sub(r"\s", "", text)) < 20:
        raise AttachmentError("PDF without text layer (scan?), content cannot be checked")
    return text


def attachment_text(f):
    """file part -> (filename, kind, plain text, note). Raises AttachmentError if
    the content is not reliably available as text."""
    name = f.get("filename") or "attachment"
    data = f.get("file_data") or ""
    m = re.match(r"data:([^;,]*)((?:;[^;,]*)*),(.*)$", data, re.S)
    if not m:
        raise AttachmentError("no embedded data (URL or file_id), content cannot be checked")
    mime = (m.group(1) or mimetypes.guess_type(name)[0] or "").lower()
    try:
        raw = (base64.b64decode(m.group(3)) if ";base64" in m.group(2)
               else urllib.parse.unquote_to_bytes(m.group(3)))
    except ValueError:
        raise AttachmentError("attachment cannot be decoded")
    if mime == "application/pdf" or raw[:5] == b"%PDF-":
        text, kind = pdf_to_text(raw), "PDF"
    elif mime.startswith("text/") or mime in TEXT_MIMES:
        if b"\x00" in raw[:4096]:
            raise AttachmentError("declared as text but binary")
        text, kind = raw.decode("utf-8", "replace"), "text"
    else:
        raise AttachmentError(f"file type {mime or 'unknown'} is not checked")
    note = ""
    if len(text) > ATTACH_MAX:
        text = text[:ATTACH_MAX]
        note = f", truncated after {ATTACH_MAX} characters"
    return name, kind, text, note


def file_part_to_text(part, mp):
    """Ersetzt einen file-Part durch einen pseudonymisierten Text-Part."""
    f = part.get("file") or {}
    try:
        name, kind, text, note = attachment_text(f)
    except AttachmentError as e:
        STATS["attachments_blocked"] += 1
        name = f.get("filename") or "attachment"
        log(f"attachment blocked: {e}")
        return {"type": "text", "text": mp.pseudonymize(
            f"[Attachment \"{name}\" was not forwarded by the privacy proxy: {e}. "
            f"Tell the user to paste the content as text.]")}
    STATS["attachments_extracted"] += 1
    # The filename goes through detection too: "Contract_Julia_Hartmann.pdf"
    head = mp.pseudonymize(f"[Attachment \"{name}\" ({kind}{note}), text content "
                           f"extracted by the privacy proxy:]")
    return {"type": "text", "text": head + "\n" + mp.pseudonymize(text)}


def pseudonymize_body(body, mp):
    for msg in body.get("messages", []):
        if msg.get("role") not in ROLES:
            continue
        c = msg.get("content")
        if isinstance(c, str):
            msg["content"] = mp.pseudonymize(c)
        elif isinstance(c, list):
            for i, part in enumerate(c):
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    part["text"] = mp.pseudonymize(part.get("text", ""))
                elif part.get("type") == "file":
                    c[i] = file_part_to_text(part, mp)
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            if isinstance(fn.get("arguments"), str):
                fn["arguments"] = _pseudo_json_string(fn["arguments"], mp)
    return body


def _pseudo_json_string(s, mp):
    """Tool arguments: pseudonymize only string values inside the JSON."""
    try:
        obj = json.loads(s)
    except ValueError:
        return mp.pseudonymize(s)

    def walk(o):
        if isinstance(o, str):
            return mp.pseudonymize(o)
        if isinstance(o, list):
            return [walk(x) for x in o]
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        return o
    return json.dumps(walk(obj), ensure_ascii=False)


def restore_message(msg, mp):
    for k in ("content", "reasoning", "reasoning_content"):
        if isinstance(msg.get(k), str):
            msg[k] = mp.restore(msg[k])
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        if isinstance(fn.get("arguments"), str):
            fn["arguments"] = mp.restore(fn["arguments"], json_escape=True)


class StreamRestorer:
    """Holds back a tail that could be a truncated placeholder."""
    TAIL = re.compile(r"\[?[A-Z][A-Z0-9_]*\]?$|\[$")

    def __init__(self, mp, json_escape=False):
        self.mp, self.esc, self.buf = mp, json_escape, ""

    def feed(self, text):
        self.buf += text
        m = self.TAIL.search(self.buf)
        if m and len(self.buf) - m.start() <= 48 and not self.buf.endswith("]"):
            emit, self.buf = self.buf[:m.start()], self.buf[m.start():]
        else:
            emit, self.buf = self.buf, ""
        return self.mp.restore(emit, self.esc)

    def flush(self):
        emit, self.buf = self.buf, ""
        return self.mp.restore(emit, self.esc)


# --------------------------------------------------------------- Debug API
#
# For the UI in ui/. Reachable only from PSEUDO_DEBUG_ALLOW
# (default: localhost only), because /debug/audit serves the sensitive audit log.
#
#   GET  /debug/config                 settings, counters, PII health
#   POST /debug/detect {text, threshold?}   all candidates with their decision
#   POST /debug/preview {messages}     body as the upstream would see it
#   GET  /debug/audit?days=&limit=&q=  audit entries, newest first
#   GET  /debug/audit/item?id=         one entry, blobs resolved
#   GET  /debug/audit/leaks?id=&threshold=  second pass, like "report"
#   GET  /ui/...                       built UI from PSEUDO_UI_DIR

DEBUG_ALLOW = {a.strip() for a in os.environ.get("PSEUDO_DEBUG_ALLOW", "127.0.0.1,::1").split(",") if a.strip()}
UI_DIR = os.path.realpath(os.path.expanduser(os.environ.get("PSEUDO_UI_DIR", "~/pseudo-ui")))
STARTED = time.time()
STATS = collections.Counter()
AUDIT_FILE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}\.jsonl$")
BLOB_RX = re.compile(r"^blob:([0-9a-f]{64})$")


def _norm_label(label):
    norm = re.sub(r"[^A-Z0-9]+", "_", label.upper()).strip("_")
    return LABEL_ALIASES.get(norm, norm)


def detect_debug(text, threshold=None):
    """Like detect(), but without cache and with every rejected decision."""
    thr = THRESHOLD if threshold is None else float(threshold)
    cands = []
    for label, rx in REGEXES:
        for m in rx.finditer(text):
            cands.append({"start": m.start(), "end": m.end(), "label": label,
                          "score": 1.0, "source": "regex"})
    t0 = time.time()
    # Ask GLiNER with a slightly lower threshold so "just below" becomes visible
    for s, e, label, score in gliner_spans(text, min(thr, 0.3)):
        cands.append({"start": s, "end": e, "label": label, "score": round(score, 3),
                      "source": "gliner"})
    gliner_ms = round((time.time() - t0) * 1000)
    for c in cands:
        c["text"] = text[c["start"]:c["end"]]
        c["norm_label"] = _norm_label(c["label"])
    order = sorted(range(len(cands)),
                   key=lambda i: (-(cands[i]["end"] - cands[i]["start"]), -cands[i]["score"]))
    taken = []
    for i in order:
        c = cands[i]
        if c["label"].lower() in SKIP_LABELS:
            c["status"] = "skip_label"
            continue
        if c["score"] < thr:
            c["status"] = "below_threshold"
            continue
        s, e = c["start"], c["end"]
        if any(s < te and ts < e for ts, te, _ in taken):
            c["status"] = "overlap"
            continue
        frag = text[s:e]
        ls = len(frag) - len(frag.lstrip(" \t\n.,;:\"'"))
        rs = len(frag) - len(frag.rstrip(" \t\n.,;:\"'"))
        core = frag[ls:len(frag) - rs]
        # Only cut parentheses that are not paired within the span: "(07531) 57 32" keeps
        # the "(", "(0171 1234567)" loses both.
        while core.startswith("(") and ")" not in core:
            core, ls = core[1:], ls + 1
        while core.endswith(")") and "(" not in core:
            core, rs = core[:-1], rs + 1
        while core.startswith(")") or core.endswith("("):
            if core.startswith(")"):
                core, ls = core[1:], ls + 1
            else:
                core, rs = core[:-1], rs + 1
        s, e = s + ls, e - rs
        if e - s < 2:
            c["status"] = "too_short"
            continue
        c["status"] = "kept"
        c["final_start"], c["final_end"] = s, e
        taken.append((s, e, c))
    taken.sort(key=lambda x: x[0])
    mp, out, pos = Mapping(), [], 0
    segments = []
    for s, e, c in taken:
        out.append(text[pos:s])
        ph = mp.placeholder(text[s:e], c["norm_label"])
        c["placeholder"] = ph
        segments.append({"start": s, "end": e, "placeholder": ph, "label": c["norm_label"]})
        out.append(ph)
        pos = e
    out.append(text[pos:])
    cands.sort(key=lambda c: (c["start"], c["end"]))
    return {"threshold": thr, "gliner_ms": gliner_ms, "candidates": cands,
            "segments": segments, "pseudonymized": "".join(out), "mapping": mp.rev}


def _resolve_blob(v):
    m = BLOB_RX.match(v) if isinstance(v, str) else None
    if not m:
        return v
    try:
        with open(os.path.join(AUDIT_DIR, "blobs", m.group(1) + ".txt")) as f:
            return f.read()
    except OSError:
        return "[blob fehlt]"


def _audit_files(days):
    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))
    try:
        names = sorted(n for n in os.listdir(AUDIT_DIR) if AUDIT_FILE_RX.match(n))
    except OSError:
        return []
    return [n for n in names if n[:10] >= cutoff]


def _snippet(c, n=160):
    if isinstance(c, list):
        c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    if not isinstance(c, str) or c.startswith("blob:"):
        return ""
    c = " ".join(c.split())
    return c[:n] + ("…" if len(c) > n else "")


def audit_list(days=1, limit=200, q=""):
    q = (q or "").lower()
    out = []
    for name in reversed(_audit_files(days)):
        with open(os.path.join(AUDIT_DIR, name)) as f:
            lines = f.readlines()
        for i in range(len(lines), 0, -1):
            line = lines[i - 1]
            if q and q not in line.lower():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            msgs = rec.get("sent_messages") or []
            last_user = next((m for m in reversed(msgs) if m.get("role") == "user"), {})
            recv = (rec.get("received") or [{}])[0] or {}
            out.append({
                "id": f"{name}:{i}", "ts": rec.get("ts"), "client": rec.get("client"),
                "model_requested": rec.get("model_requested"), "model_used": rec.get("model_used"),
                "status": rec.get("status"), "stream": rec.get("stream"),
                "counts": rec.get("counts") or {}, "attempts": rec.get("attempts") or [],
                "detect_s": rec.get("detect_s"), "latency_s": rec.get("latency_s"),
                "n_messages": len(msgs), "usage": rec.get("usage"),
                "last_user": _snippet(last_user.get("content")),
                "answer": _snippet(recv.get("content")) if isinstance(recv, dict) else "",
                "has_tool_calls": bool(isinstance(recv, dict) and recv.get("tool_calls")),
            })
            if len(out) >= limit:
                return out
    return out


def audit_get(rid):
    name, _, line = (rid or "").rpartition(":")
    if not AUDIT_FILE_RX.match(name) or not line.isdigit():
        raise KeyError("bad id")
    with open(os.path.join(AUDIT_DIR, name)) as f:
        for i, l in enumerate(f, 1):
            if i == int(line):
                rec = json.loads(l)
                break
        else:
            raise KeyError("not found")
    for m in rec.get("sent_messages") or []:
        m["content"] = _resolve_blob(m.get("content"))
    if rec.get("sent_tools"):
        try:
            rec["sent_tools"] = json.loads(_resolve_blob(rec["sent_tools"]))
        except ValueError:
            pass
    rec["id"] = rid
    return rec


def audit_leaks(rec, threshold=0.3):
    """Second pass over what was sent: whatever is still PII now was a leak."""
    leaks, seen = [], set()

    def texts():
        for i, m in enumerate(rec.get("sent_messages") or []):
            if m.get("role") == "system":
                continue
            c = m.get("content")
            if isinstance(c, str):
                yield i, m.get("role"), c
            elif isinstance(c, list):
                for p in c:
                    if isinstance(p, dict) and p.get("type") == "text":
                        yield i, m.get("role"), p.get("text", "")
            for tc in m.get("tool_calls") or []:
                yield i, "tool_args", (tc.get("function") or {}).get("arguments", "")
        for r in rec.get("received") or []:
            if isinstance(r, dict) and r.get("content"):
                yield -1, "antwort", r["content"]

    for idx, src, t in texts():
        if not t or not t.strip() or t in seen:
            continue
        seen.add(t)
        for s, e, label, score in gliner_spans(t, threshold):
            if label.lower() in SKIP_LABELS:
                continue
            frag = t[s:e]
            if PH_RX.search(frag):
                continue
            leaks.append({"message": idx, "source": src, "label": label,
                          "score": round(score, 3), "text": frag,
                          "context": t[max(0, s - 60):e + 60]})
    return leaks


def pii_health():
    t0 = time.time()
    try:
        with urllib.request.urlopen(PII_URL + "/health", timeout=5) as r:
            body = json.load(r)
            return {"ok": r.status == 200, "ms": round((time.time() - t0) * 1000), "body": body}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "ms": round((time.time() - t0) * 1000), "error": str(e)}


def debug_config():
    return {
        "port": PORT, "upstream": UPSTREAM, "pii_url": PII_URL, "roles": sorted(ROLES),
        "threshold": THRESHOLD, "fail_open": FAIL_OPEN, "fallback_models": FALLBACK_MODELS,
        "retry_status": sorted(RETRY_STATUS), "skip_labels": sorted(SKIP_LABELS),
        "regex_labels": [l for l, _ in REGEXES], "label_aliases": LABEL_ALIASES,
        "audit": {"on": AUDIT_ON, "dir": AUDIT_DIR, "days": AUDIT_DAYS,
                  "files": _audit_files(AUDIT_DAYS)},
        "default_headers": list(DEFAULT_HEADERS), "placeholder_note": PLACEHOLDER_NOTE,
        "span_cache": len(SPAN_CACHE.d), "uptime_s": round(time.time() - STARTED),
        "stats": dict(STATS), "pii": pii_health(),
    }


# --------------------------------------------------------------- HTTP

def open_upstream(method, path, headers, data):
    u = urllib.parse.urlsplit(UPSTREAM + path)
    cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
    conn = cls(u.netloc, timeout=600)
    target = u.path + (("?" + u.query) if u.query else "")
    conn.request(method, target, body=data, headers=headers)
    return conn, conn.getresponse()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        log("%s %s" % (self.address_string(), fmt % args))

    def _send_json(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _fwd_headers(self):
        h = {k: v for k, v in self.headers.items() if k.lower() in PASS_HEADERS}
        present = {k.lower() for k in h}
        for k, v in DEFAULT_HEADERS.items():
            if k.lower() not in present:
                h[k] = v
        h["Accept-Encoding"] = "identity"
        return h

    def _notice(self, body, text):
        """Answer in chat format instead of an error code (see FALLBACK_MODELS)."""
        msg = "\u26a0\ufe0f [pseudonymization proxy] " + text
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for ev in ({"choices": [{"index": 0, "delta": {"role": "assistant", "content": msg}}]},
                       {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}):
                b = ("data: " + json.dumps(ev, ensure_ascii=False) + "\n\n").encode()
                self.wfile.write(b"%x\r\n%s\r\n" % (len(b), b))
            b = b"data: [DONE]\n\n"
            self.wfile.write(b"%x\r\n%s\r\n0\r\n\r\n" % (len(b), b))
            return
        return self._send_json(200, {"object": "chat.completion", "model": "pseudo-proxy",
                                     "choices": [{"index": 0, "finish_reason": "stop",
                                                  "message": {"role": "assistant", "content": msg}}]})

    def _path(self):
        p = self.path
        return p[3:] if p.startswith("/v1/") else p

    def do_GET(self):
        if self.path.startswith(("/debug/", "/ui")):
            return self._debug("GET", None)
        if self.path == "/health":
            try:
                with urllib.request.urlopen(PII_URL + "/health", timeout=5) as r:
                    ok = r.status == 200
            except Exception:  # noqa: BLE001
                ok = False
            return self._send_json(200 if ok else 503,
                                   {"ok": ok, "upstream": UPSTREAM, "roles": sorted(ROLES)})
        conn, resp = open_upstream("GET", self._path(), self._fwd_headers(), None)
        data = resp.read()
        self.send_response(resp.status)
        self.send_header("Content-Type", resp.getheader("Content-Type", "application/json"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        conn.close()

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n)
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            return self._send_json(400, {"error": "invalid json"})

        if self.path.startswith("/debug/"):
            return self._debug("POST", body)

        # Debug/test endpoint: shows what the upstream would see
        if self.path == "/pseudonymize":
            mp = Mapping()
            try:
                text = mp.pseudonymize(body.get("text", ""))
            except DetectorDown as e:
                return self._send_json(503, {"error": f"pii service down: {e}"})
            return self._send_json(200, {"text": text, "mapping": mp.rev})

        if not self._path().endswith("/chat/completions"):
            return self._send_json(404, {"error": "only /v1/chat/completions is proxied"})

        mp = Mapping()
        t0 = time.time()
        STATS["requests"] += 1
        try:
            pseudonymize_body(body, mp)
        except DetectorDown as e:
            if not FAIL_OPEN:
                STATS["refused_pii_down"] += 1
                log(f"PII service down, refusing: {e}")
                audit_write({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "client": self.client_address[0],
                         "status": "refused_pii_down"}, None)
            return self._notice(body, "PII detection on :9111 is not reachable. "
                                    "The message was NOT sent to the external model.")
            log(f"PII service down, FAIL_OPEN -> forwarding unfiltered: {e}")
            mp = Mapping()
        if mp.rev:
            add_placeholder_note(body)
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "client": self.client_address[0],
               "model_requested": body.get("model"), "stream": bool(body.get("stream")),
               "counts": dict(mp.count), "detect_s": round(time.time() - t0, 3),
               "attempts": [], "status": None}
        log(f"pseudonymized {sum(mp.count.values())} values "
            f"({', '.join(f'{k}:{v}' for k, v in sorted(mp.count.items()))}) "
            f"in {time.time() - t0:.2f}s")
        STATS["replaced_values"] += sum(mp.count.values())

        models = [body.get("model")] + [m for m in FALLBACK_MODELS if m != body.get("model")]
        last = ""
        for model in models:
            body["model"] = model
            data = json.dumps(body, ensure_ascii=False).encode()
            h = self._fwd_headers()
            h["Content-Type"] = "application/json"
            h["Content-Length"] = str(len(data))
            try:
                conn, resp = open_upstream("POST", self._path(), h, data)
            except OSError as e:
                last = f"{model}: {e}"
                rec["attempts"].append(last)
                log(f"upstream unreachable ({last}), next model")
                continue
            if resp.status in RETRY_STATUS:
                last = f"{model}: HTTP {resp.status}"
                rec["attempts"].append(last)
                resp.read()
                conn.close()
                log(f"upstream {last}, next model")
                continue
            if "text/event-stream" not in resp.getheader("Content-Type", ""):
                # OpenRouter sometimes returns 200 with {"error": ...} and no choices
                buffered = resp.read()
                try:
                    peek = json.loads(buffered)
                except ValueError:
                    peek = {}
                if isinstance(peek, dict) and peek.get("error") and not peek.get("choices"):
                    last = f"{model}: 200 with error body"
                    rec["attempts"].append(last)
                    conn.close()
                    log(f"upstream {last}, next model")
                    continue
                resp.read = lambda b=buffered: b  # already read
            break
        else:
            rec["status"] = "all_failed"
            STATS["all_failed"] += 1
            audit_write(rec, body)
            return self._notice(body, "No model answered (last: " + last + "). "
                                "Please try again shortly. Nothing was sent in plain text.")
        if model != models[0]:
            STATS["fallback_used"] += 1
            log(f"fallback used: {model}")
        ctype = resp.getheader("Content-Type", "")
        rec["model_used"] = model
        rec["status"] = resp.status
        rec["latency_s"] = None
        t1 = time.time()
        try:
            if "text/event-stream" in ctype:
                rec["received"] = self._relay_stream(resp, mp)
            else:
                out = resp.read()
                try:
                    obj = json.loads(out)
                    rec["received"] = [json.loads(json.dumps(ch.get("message")))
                                       for ch in obj.get("choices", [])]
                    rec["usage"] = obj.get("usage")
                    for ch in obj.get("choices", []):
                        if isinstance(ch.get("message"), dict):
                            restore_message(ch["message"], mp)
                    out = json.dumps(obj, ensure_ascii=False).encode()
                except ValueError:
                    pass
                self.send_response(resp.status)
                self.send_header("Content-Type", ctype or "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)
        finally:
            conn.close()
            rec["latency_s"] = round(time.time() - t1, 2)
            audit_write(rec, body)

    def _debug(self, method, body):
        if "*" not in DEBUG_ALLOW and self.client_address[0] not in DEBUG_ALLOW:
            return self._send_json(403, {"error": "debug only from " + ",".join(sorted(DEBUG_ALLOW))})
        u = urllib.parse.urlsplit(self.path)
        qs = {k: v[-1] for k, v in urllib.parse.parse_qs(u.query).items()}
        path = u.path
        if method == "GET" and (path == "/ui" or path.startswith("/ui/")):
            return self._static(path[3:].lstrip("/"))
        try:
            if method == "GET" and path == "/debug/config":
                return self._send_json(200, debug_config())
            if method == "GET" and path == "/debug/audit":
                return self._send_json(200, audit_list(int(qs.get("days", 1)),
                                                       int(qs.get("limit", 200)), qs.get("q", "")))
            if method == "GET" and path == "/debug/audit/item":
                return self._send_json(200, audit_get(qs.get("id")))
            if method == "GET" and path == "/debug/audit/leaks":
                rec = audit_get(qs.get("id"))
                return self._send_json(200, audit_leaks(rec, float(qs.get("threshold", 0.3))))
            if method == "POST" and path == "/debug/detect":
                return self._send_json(200, detect_debug(body.get("text", ""), body.get("threshold")))
            if method == "POST" and path == "/debug/preview":
                mp, t0 = Mapping(), time.time()
                sent = json.loads(json.dumps({"messages": body.get("messages", [])}))
                pseudonymize_body(sent, mp)
                if mp.rev:
                    add_placeholder_note(sent)
                return self._send_json(200, {"body": sent, "mapping": mp.rev, "counts": mp.count,
                                             "ms": round((time.time() - t0) * 1000)})
        except DetectorDown as e:
            return self._send_json(503, {"error": f"pii service down: {e}"})
        except KeyError as e:
            return self._send_json(404, {"error": str(e)})
        except (ValueError, TypeError) as e:
            return self._send_json(400, {"error": str(e)})
        return self._send_json(404, {"error": "unknown debug endpoint"})

    def _static(self, rel):
        if not os.path.isdir(UI_DIR):
            return self._send_json(404, {"error": f"UI not built/copied to {UI_DIR}"})
        fp = os.path.realpath(os.path.join(UI_DIR, rel or "index.html"))
        if not fp.startswith(UI_DIR + os.sep) or not os.path.isfile(fp):
            fp = os.path.join(UI_DIR, "index.html")  # SPA-Fallback
        with open(fp, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(fp)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache" if fp.endswith(".html") else "max-age=86400")
        self.end_headers()
        self.wfile.write(data)

    def _relay_stream(self, resp, mp):
        self.send_response(resp.status)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def write(line):
            b = line.encode()
            self.wfile.write(b"%x\r\n%s\r\n" % (len(b), b))
            self.wfile.flush()

        restorers = {}  # (choice, field[, tool_idx]) -> StreamRestorer
        raw_acc = {"content": "", "reasoning": "", "tool_calls": {}}

        def r(key, esc=False):
            if key not in restorers:
                restorers[key] = StreamRestorer(mp, esc)
            return restorers[key]

        def flush_choice(ci, delta):
            for key, sr in list(restorers.items()):
                if key[0] != ci:
                    continue
                rest = sr.flush()
                if not rest:
                    continue
                if key[1] == "tool":
                    tcs = delta.setdefault("tool_calls", [])
                    tcs.append({"index": key[2], "function": {"arguments": rest}})
                else:
                    delta[key[1]] = rest + (delta.get(key[1]) or "")

        for raw in resp:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                if line.startswith("data:"):
                    # Still deliver leftovers when there was no finish_reason chunk
                    for ci in {k[0] for k in restorers}:
                        delta = {}
                        flush_choice(ci, delta)
                        if delta:
                            write("data: " + json.dumps({"choices": [
                                {"index": ci, "delta": delta}]}, ensure_ascii=False) + "\n\n")
                write(line + "\n")
                continue
            try:
                obj = json.loads(line[5:])
            except ValueError:
                write(line + "\n")
                continue
            for ch in obj.get("choices", []):
                ci = ch.get("index", 0)
                delta = ch.get("delta") or {}
                for f in ("content", "reasoning", "reasoning_content"):
                    if isinstance(delta.get(f), str):
                        if ci == 0:
                            raw_acc["content" if f == "content" else "reasoning"] += delta[f]
                        delta[f] = r((ci, f)).feed(delta[f])
                for tc in delta.get("tool_calls") or []:
                    fn = tc.get("function") or {}
                    if ci == 0:
                        acc = raw_acc["tool_calls"].setdefault(str(tc.get("index", 0)), {"name": "", "arguments": ""})
                        acc["name"] += fn.get("name") or ""
                        acc["arguments"] += fn.get("arguments") or ""
                    if isinstance(fn.get("arguments"), str):
                        fn["arguments"] = r((ci, "tool", tc.get("index", 0)), True).feed(fn["arguments"])
                if ch.get("finish_reason"):
                    flush_choice(ci, delta)
                    for k in [k for k in restorers if k[0] == ci]:
                        del restorers[k]
                if isinstance(ch.get("message"), dict):
                    restore_message(ch["message"], mp)
            write("data: " + json.dumps(obj, ensure_ascii=False) + "\n")
        self.wfile.write(b"0\r\n\r\n")
        return [raw_acc]


if __name__ == "__main__":
    log(f"pseudo-proxy :{PORT} -> {UPSTREAM}, PII {PII_URL}, roles {sorted(ROLES)}, "
        f"fail_open={FAIL_OPEN}, fallbacks={len(FALLBACK_MODELS)}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
