#!/usr/bin/env python3
"""Re-implementation of :9111 (/extract, /health) for benchmark runs without VPN.

Same model (fastino/gliner2-privacy-filter-PII-multi), same windows
(2000 characters, 300 overlap). The 19 default labels of the real service are
estimated here; results are therefore an approximation, a run against the real
proxy is authoritative (bench.py --proxy http://<proxy-host>:9112).

  pip install torch --index-url https://download.pytorch.org/whl/cpu
  pip install gliner2 transformers peft
  ./pii-local.py 9111
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from gliner2 import GLiNER2

LABELS = ["person", "date_of_birth", "email", "phone_number", "address", "city",
          "postal_code", "government_id", "passport_number", "tax_id", "iban",
          "account_number", "payment_card", "username", "ip_address", "password",
          "secret", "api_key", "access_token"]
WIN, OVL = 2000, 300
M = GLiNER2.from_pretrained("fastino/gliner2-privacy-filter-PII-multi")


def windows(text):
    if len(text) <= WIN:
        yield 0, text
        return
    s = 0
    while s < len(text):
        e = min(len(text), s + WIN)
        if e < len(text):
            sp = text.rfind(" ", s + WIN - OVL, e)
            e = sp if sp > s else e
        yield s, text[s:e]
        if e >= len(text):
            break
        ns = e - OVL
        sp = text.find(" ", ns)
        s = sp + 1 if 0 <= sp < e else ns


def extract(text, labels, thr):
    best = {}
    for off, chunk in windows(text):
        r = M.extract_entities(chunk, labels, threshold=thr, include_confidence=True,
                               include_spans=True)
        for label, items in (r.get("entities") or {}).items():
            for it in items:
                s, e = off + it["start"], off + it["end"]
                sc = float(it.get("confidence", 1.0))
                if (s, e) not in best or best[(s, e)][1] < sc:
                    best[(s, e)] = (label, sc)
    return [{"start": s, "end": e, "label": l, "score": sc, "text": text[s:e]}
            for (s, e), (l, sc) in sorted(best.items())]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        d = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(d)))
        self.end_headers()
        self.wfile.write(d)

    def do_GET(self):
        self._send({"ok": True, "labels": LABELS})

    def do_POST(self):
        b = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self._send({"entities": extract(b.get("text", ""), b.get("labels") or LABELS,
                                        float(b.get("threshold", 0.5)))})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 9111), H).serve_forever()
