#!/usr/bin/env python3
"""Evaluation of the pseudonymization proxy's audit log.

  audit.py report [--days 7] [--threshold 0.3]
      Requests, models, fallbacks, replaced values -- and SUSPECTED LEAKS:
      everything a second pass (lower threshold) still recognizes as personal
      data in the text that was already sent. Go through the list by hand:
      real hits = the proxy's miss rate, the rest = false alarms.

  audit.py show [--days 1] [-n 5]
      The latest requests, readable: what went out, what came back.

  audit.py export OUT.jsonl [--days 30]
      Conversations in OpenAI chat format (pseudonymized) for fine-tuning.
      System prompts and tool definitions are resolved from blobs/.

Standard library only. Reads PSEUDO_AUDIT_DIR (~/pseudo-audit) and, for "report",
queries the PII service at PSEUDO_PII_URL (http://127.0.0.1:9111).
"""
import argparse
import collections
import glob
import json
import os
import re
import time
import urllib.request

AUDIT_DIR = os.path.expanduser(os.environ.get("PSEUDO_AUDIT_DIR", "~/pseudo-audit"))
PII_URL = os.environ.get("PSEUDO_PII_URL", "http://127.0.0.1:9111").rstrip("/")
PH = re.compile(r"\[?\b[A-Z][A-Z0-9_]*_\d+\b\]?")
SKIP = {"date", "time", "age", "gender", "nationality", "language", "religion",
        "occupation", "job_title"}


def records(days):
    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))
    for path in sorted(glob.glob(os.path.join(AUDIT_DIR, "*.jsonl"))):
        if os.path.basename(path)[:10] < cutoff:
            continue
        with open(path) as f:
            for i, line in enumerate(f, 1):
                try:
                    yield f"{os.path.basename(path)}:{i}", json.loads(line)
                except ValueError:
                    pass


def resolve(v):
    if isinstance(v, str) and v.startswith("blob:"):
        try:
            with open(os.path.join(AUDIT_DIR, "blobs", v[5:] + ".txt")) as f:
                return f.read()
        except OSError:
            return "[blob fehlt]"
    return v


def texts(rec):
    """(source, text) for everything the proxy should have pseudonymized."""
    for i, m in enumerate(rec.get("sent_messages", [])):
        if m.get("role") == "system":
            continue  # system prompt is deliberately not pseudonymized
        c = m.get("content")
        if isinstance(c, str):
            yield f"msg{i}/{m.get('role')}", c
        elif isinstance(c, list):
            for p in c:
                if isinstance(p, dict) and p.get("type") == "text":
                    yield f"msg{i}/{m.get('role')}", p.get("text", "")
        for tc in m.get("tool_calls") or []:
            yield f"msg{i}/tool_args", (tc.get("function") or {}).get("arguments", "")
    for r in rec.get("received") or []:
        if isinstance(r, dict) and r.get("content"):
            yield "antwort", r["content"]


def extract(text, threshold):
    req = urllib.request.Request(PII_URL + "/extract",
                                 data=json.dumps({"text": text, "threshold": threshold}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r).get("entities", [])


def cmd_report(a):
    n = 0
    status = collections.Counter()
    used = collections.Counter()
    counts = collections.Counter()
    fallbacks = 0
    leaks = []
    seen = set()
    for where, rec in records(a.days):
        n += 1
        status[str(rec.get("status"))] += 1
        if rec.get("model_used"):
            used[rec["model_used"]] += 1
        if rec.get("model_used") and rec.get("model_used") != rec.get("model_requested"):
            fallbacks += 1
        counts.update(rec.get("counts") or {})
        for src, t in texts(rec):
            if not t or not t.strip() or t in seen:
                continue
            seen.add(t)  # history repeats every turn -> check only once
            for e in extract(t, a.threshold):
                if e.get("label", "").lower() in SKIP:
                    continue
                frag = t[e["start"]:e["end"]]
                if PH.fullmatch(frag.strip()) or PH.search(frag):
                    continue
                leaks.append((where, src, e.get("label"), round(e.get("score", 0), 2), frag))
    print(f"Requests: {n}   proxy fallbacks: {fallbacks}   status: {dict(status)}")
    print("Models:", ", ".join(f"{m} {c}" for m, c in used.most_common()))
    print("Replaced:", ", ".join(f"{k} {v}" for k, v in counts.most_common()) or "nothing")
    total = sum(counts.values())
    print(f"\nSuspected leaks (second pass, threshold {a.threshold}): {len(leaks)}"
          + (f"  -> roughly {len(leaks) / (total + len(leaks)):.1%} of detected values" if total else ""))
    for where, src, label, score, frag in leaks:
        print(f"  {where:22s} {src:16s} {label:18s} {score:.2f}  {frag!r}")


def cmd_show(a):
    recs = list(records(a.days))[-a.n:]
    for where, rec in recs:
        print("=" * 80)
        print(where, rec.get("ts"), rec.get("client"), "->", rec.get("model_used"),
              "| status", rec.get("status"), "| ersetzt", rec.get("counts"),
              "| Versuche", rec.get("attempts") or "-")
        for m in rec.get("sent_messages", [])[-3:]:
            c = resolve(m.get("content"))
            c = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
            print(f"  >> {m.get('role')}: {c[:400]}")
        for r in rec.get("received") or []:
            print(f"  << {json.dumps(r, ensure_ascii=False)[:600]}")


def cmd_export(a):
    k = 0
    with open(a.out, "w") as f:
        for _, rec in records(a.days):
            if rec.get("status") != 200 or not rec.get("received"):
                continue
            msgs = []
            for m in rec.get("sent_messages", []):
                m = dict(m)
                m["content"] = resolve(m.get("content"))
                msgs.append(m)
            r = rec["received"][0]
            ans = {"role": "assistant", "content": r.get("content") or ""}
            tcs = r.get("tool_calls")
            if isinstance(tcs, dict):  # Stream-Format aus dem Proxy
                tcs = [{"type": "function", "function": v} for _, v in sorted(tcs.items())]
            if tcs:
                ans["tool_calls"] = tcs
            row = {"messages": msgs + [ans], "model": rec.get("model_used")}
            if rec.get("sent_tools"):
                row["tools"] = json.loads(resolve(rec["sent_tools"]))
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            k += 1
    os.chmod(a.out, 0o600)
    print(f"{k} conversations -> {a.out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("report")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--threshold", type=float, default=0.3)
    p.set_defaults(fn=cmd_report)
    p = sub.add_parser("show")
    p.add_argument("--days", type=int, default=1)
    p.add_argument("-n", type=int, default=5)
    p.set_defaults(fn=cmd_show)
    p = sub.add_parser("export")
    p.add_argument("out")
    p.add_argument("--days", type=int, default=30)
    p.set_defaults(fn=cmd_export)
    a = ap.parse_args()
    a.fn(a)
