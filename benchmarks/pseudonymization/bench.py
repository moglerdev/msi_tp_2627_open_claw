#!/usr/bin/env python3
"""Benchmark for the pseudonymization proxy (:9112).

Two parts:

  Detection  (levels 0-4) via POST /pseudonymize: shows exactly what the
             upstream would see. For each case it checks whether a PII
             substring is still in the text (leak), whether harmless parts
             were destroyed (false positive) and whether the reverse mapping
             reproduces the original text.

  Transport  (level 5, --e2e) starts the proxy from ../../apps/pseudonymization-proxy/proxy.py
             locally with a capture server as upstream and sends real
             /v1/chat/completions requests: text parts, tool calls,
             tool results, system role, PDF as file part, image,
             streaming reverse mapping. The raw body the upstream receives is
             checked, including decoded base64 attachments.
             Nothing goes to OpenRouter, no audit log.

Usage:

  # against a running proxy (network access to it required)
  ./bench.py --proxy http://<proxy-host>:9112

  # on the GPU host itself, everything including end-to-end
  ./bench.py --local --pii-url http://127.0.0.1:9111 --e2e

  # result as Markdown/JSON
  ./bench.py ... --md results.md --json results.json

Standard library only (pdftotext optional for the PDF extraction case).
The test inputs are German on purpose: the detector is evaluated on German text.
"""
import argparse
import base64
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cases import C  # noqa: E402

PH_RX = re.compile(r"\[([A-Z][A-Z0-9_]*?_\d+)\]")
LEVELS = {0: "false alarms", 1: "easy", 2: "medium", 3: "structured",
          4: "hard", 5: "transport"}


# ------------------------------------------------------------------ Helfer

def post(url, obj, timeout=300, headers=None):
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=json.dumps(obj).encode(), headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read()


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_http(url, secs=30):
    t0 = time.time()
    while time.time() - t0 < secs:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except urllib.error.HTTPError:
            return True
        except Exception:  # noqa: BLE001
            time.sleep(0.2)
    return False


def restore(text, mapping):
    return PH_RX.sub(lambda m: mapping.get(m.group(1), m.group(0)), text)


def make_pdf(lines):
    """Minimales einseitiges PDF, unkomprimiert, WinAnsi (Umlaute ok)."""
    def esc(s):
        b = s.encode("cp1252")
        out = ""
        for c in b:
            ch = chr(c)
            if ch in "()\\":
                out += "\\" + ch
            elif c > 126:
                out += "\\%03o" % c
            else:
                out += ch
        return out
    ops = ["BT", "/F1 11 Tf", "14 TL", "56 780 Td"]
    for ln in lines:
        ops.append("(%s) Tj T*" % esc(ln))
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for o in offs:
        out += b"%010d 00000 n \n" % o
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return bytes(out)


PDF_LINES = [
    "Arbeitsvertrag",
    "Zwischen der Muster GmbH und Frau Julia Hartmann,",
    "wohnhaft Seestraße 14, 78464 Konstanz, geboren am 15.03.1985.",
    "Steuer-ID: 12 345 678 903   Sozialversicherungsnummer: 65 170839 J 003",
    "Gehaltskonto: DE89 3704 0044 0532 0130 00",
    "Kontakt: julia.hartmann@gmx.de, Mobil 0171 2345678",
]
PDF_PII = ["Julia", "Hartmann", "Seestraße 14", "78464", "12 345 678 903",
           "170839", "DE89 3704", "julia.hartmann@gmx.de", "2345678"]


def pdf_extract_case():
    """Generate a PDF, extract it with pdftotext, append it as a detection case."""
    if not shutil.which("pdftotext"):
        return None
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "v.pdf")
        with open(p, "wb") as f:
            f.write(make_pdf(PDF_LINES))
        txt = subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True,
                             text=True).stdout
    if "Hartmann" not in txt:
        return None
    return dict(id="4-pdf-pdftotext", level=4, cat="pdf_text", text=txt,
                pii=PDF_PII, keep=["Arbeitsvertrag"], design=None)


# ------------------------------------------------------------------ Erkennung

def score_text(out, case):
    leaks = [p for p in case["pii"] if p in out]
    fps = [k for k in case["keep"] if k not in out]
    return leaks, fps


def run_detect(proxy, cases, verbose=False):
    res = []
    for c in cases:
        t0 = time.time()
        try:
            _, _, raw = post(proxy + "/pseudonymize", {"text": c["text"]})
            obj = json.loads(raw)
        except Exception as e:  # noqa: BLE001
            res.append(dict(c, error=str(e), leaks=c["pii"], fps=[], ok=False))
            print(f"  {c['id']:<22} FEHLER {e}")
            continue
        dt = time.time() - t0
        out, mapping = obj["text"], obj.get("mapping", {})
        leaks, fps = score_text(out, c)
        rt = restore(out, mapping) == c["text"]
        r = dict(id=c["id"], level=c["level"], cat=c["cat"], design=c.get("design"),
                 n_pii=len(c["pii"]), leaks=leaks, fps=fps, roundtrip=rt,
                 n_replaced=len(mapping), secs=round(dt, 2), chars=len(c["text"]),
                 out=out, ok=not leaks and not fps)
        res.append(r)
        flag = "ok " if r["ok"] else ("LECK" if leaks else "FP  ")
        extra = []
        if leaks:
            extra.append("leaks: " + ", ".join(repr(x) for x in leaks[:6]))
        if fps:
            extra.append("destroyed: " + ", ".join(repr(x) for x in fps[:4]))
        if not rt:
            extra.append("reverse mapping differs")
        if c.get("design") and leaks:
            extra.append("(expected: " + c["design"] + ")")
        print(f"  {c['id']:<22} {flag} {len(c['pii']) - len(leaks):>2}/{len(c['pii']):<2} "
              f"{dt:5.2f}s  {'; '.join(extra)}")
        if verbose:
            print("      -> " + out[:400].replace("\n", "\n         "))
    return res


# ------------------------------------------------------------------ End to end

class Capture:
    """Fake upstream: stores the body and answers with all placeholders it sees
    in the last message (so the reverse mapping can be checked). With tools=...
    as a tool call, with stream=true in 3-character chunks."""

    def __init__(self):
        self.bodies = []
        cap = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                cap.bodies.append(body)
                last = json.dumps(body["messages"][-1], ensure_ascii=False)
                phs = list(dict.fromkeys("[" + m + "]" for m in PH_RX.findall(last)))
                text = "Antwort: " + " | ".join(phs)
                if body.get("tools"):
                    msg = {"role": "assistant", "content": None, "tool_calls": [{
                        "id": "c1", "type": "function", "function": {
                            "name": "send_mail",
                            "arguments": json.dumps({"to": phs[:1], "body": text})}}]}
                else:
                    msg = {"role": "assistant", "content": text}
                if body.get("stream"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    for i in range(0, len(text), 3):
                        ev = {"choices": [{"index": 0, "delta": {"content": text[i:i + 3]}}]}
                        self.wfile.write(b"data: " + json.dumps(ev).encode() + b"\n\n")
                    ev = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
                    self.wfile.write(b"data: " + json.dumps(ev).encode() + b"\n\ndata: [DONE]\n\n")
                    self.close_connection = True
                    return
                data = json.dumps({"choices": [{"index": 0, "message": msg,
                                                "finish_reason": "stop"}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.port = free_port()
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()


def upstream_view(body):
    """Everything the upstream can read: JSON text plus decoded attachments."""
    s = json.dumps(body, ensure_ascii=False)
    for m in re.finditer(r"data:[\w/.+-]+;base64,([A-Za-z0-9+/=]+)", s):
        raw = base64.b64decode(m.group(1))
        s += "\n" + raw.decode("latin-1")
        # PDF strings in WinAnsi -> back to Unicode for the comparison
        try:
            s += "\n" + raw.decode("cp1252", "replace")
        except Exception:  # noqa: BLE001
            pass
    # resolve PDF octal escapes (\337 = ß)
    s += "\n" + re.sub(r"\\(\d{3})", lambda m: bytes([int(m.group(1), 8)]).decode("cp1252"), s)
    return s


def e2e_scenarios():
    pdf_b64 = base64.b64encode(make_pdf(PDF_LINES)).decode()
    png_b64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    S = []

    def sc(id, cat, body, pii, design=None, check=None, expect=()):
        S.append(dict(id=id, level=5, cat=cat, body=body, pii=pii, design=design, check=check,
                      expect=list(expect)))

    def att(text, filename, data):
        return {"messages": [{"role": "user", "content": [
            {"type": "text", "text": text},
            {"type": "file", "file": {"filename": filename, "file_data": data}}]}]}

    sc("5-text-parts", "content_parts", {"messages": [{"role": "user", "content": [
        {"type": "text", "text": "Bitte schreib Julia Hartmann eine Mail an julia.hartmann@gmx.de."},
        {"type": "text", "text": "Ihr Passwort Somm" "er2024! soll sie ändern."}]}]},
        ["Julia", "Hartmann", "julia.hartmann@gmx.de", "Somm" "er2024!"])
    sc("5-tool-args", "tool_calls", {"messages": [
        {"role": "user", "content": "Schick die Rechnung raus."},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "t1", "type": "function",
         "function": {"name": "send_mail", "arguments": json.dumps(
             {"to": "tobias.brenner@example.org", "name": "Tobias Brenner",
              "iban": "DE89 3704 0044 0532 0130 00"})}}]},
        {"role": "tool", "tool_call_id": "t1", "content": "gesendet"},
        {"role": "user", "content": "Danke."}]},
        ["tobias.brenner@example.org", "Tobias", "Brenner", "DE89 3704"])
    sc("5-tool-result-csv", "tool_result", {"messages": [
        {"role": "user", "content": "Lies die Kundenliste."},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "t1", "type": "function",
         "function": {"name": "read_file", "arguments": "{\"path\": \"kunden.csv\"}"}}]},
        {"role": "tool", "tool_call_id": "t1", "content": next(c["text"] for c in C if c["id"] == "3-csv-header")}]},
        ["Hartmann", "Brenner", "Yilmaz", "t.brenner@web.de", "hunter2", "DE02 1203"])
    sc("5-multiturn", "consistency", {"messages": [
        {"role": "user", "content": "Lea Vogt zieht nächste Woche um."},
        {"role": "assistant", "content": "Soll ich Lea Vogt eine Nachricht schicken?"},
        {"role": "user", "content": "Ja, an lea.vogt@t-online.de, und sag Lea Vogt, dass Tobias hilft."}]},
        ["Lea", "Vogt", "lea.vogt@t-online.de"], check="consistent")
    sc("5-system-role", "system_role", {"messages": [
        {"role": "system", "content": "Du bist der Assistent von Dr. Klara Neumann, "
                                      "erreichbar unter kneumann@htwg-konstanz.de, Tel. 07531 206512."},
        {"role": "user", "content": "Wer bist du?"}]},
        ["Klara", "Neumann", "kneumann@htwg-konstanz.de", "206512"],
        design="PSEUDO_ROLES ohne system (Bot-Config, ~27k Token)")
    sc("5-pdf-file-part", "pdf_attachment",
       att("Fass den Vertrag zusammen.", "arbeitsvertrag.pdf", "data:application/pdf;base64," + pdf_b64),
       PDF_PII, check="no_file", expect=["Arbeitsvertrag", "Gehaltskonto"])
    sc("5-pdf-filename", "pdf_attachment",
       att("Prüf das bitte.", "Vertrag Julia Hartmann.pdf", "data:application/pdf;base64," + pdf_b64),
       PDF_PII, check="no_file", expect=["Gehaltskonto"])
    sc("5-pdf-scan", "pdf_attachment",
       att("Was steht im Scan?", "scan.pdf", "data:application/pdf;base64,"
           + base64.b64encode(make_pdf([])).decode()),
       [], check="no_file", expect=["not forwarded", "text layer"])
    sc("5-pdf-url", "pdf_attachment",
       att("Lies das PDF.", "x.pdf", "https://example.org/Julia-Hartmann-Lebenslauf.pdf"),
       ["Julia-Hartmann-Lebenslauf"], check="no_file", expect=["not forwarded"])
    sc("5-csv-file-part", "file_attachment",
       att("Werte die Liste aus.", "kunden.csv", "data:text/csv;base64," + base64.b64encode(
           next(c["text"] for c in C if c["id"] == "3-csv-header").encode()).decode()),
       ["Hartmann", "Brenner", "Yilmaz", "t.brenner@web.de", "hunter2", "DE02 1203"],
       check="no_file", expect=["Name;E-Mail;Telefon"])
    sc("5-docx-file-part", "file_attachment",
       att("Lies das Dokument.", "brief.docx",
           "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,"
           + base64.b64encode(b"PK\x03\x04Julia Hartmann Seestra\xc3\x9fe 14").decode()),
       ["Julia", "Hartmann", "Seestraße 14"], check="no_file", expect=["not forwarded"])
    sc("5-image-part", "image_attachment", {"messages": [{"role": "user", "content": [
        {"type": "text", "text": "Was steht auf dem Foto meines Ausweises?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + png_b64}}]}]},
        [], check="image_unchanged")
    sc("5-stream-restore", "restore", {"stream": True, "messages": [
        {"role": "user", "content": "Grüß Mehmet Yilmaz und schreib an myilmaz@outlook.com."}]},
        ["Mehmet", "Yilmaz", "myilmaz@outlook.com"], check="restore")
    sc("5-tool-restore", "restore", {"tools": [{"type": "function", "function": {
        "name": "send_mail", "parameters": {"type": "object"}}}], "messages": [
        {"role": "user", "content": "Schick \"Hallo\" an jonas.keller@gmail.com, Gruß an Jonas Keller."}]},
        ["jonas.keller@gmail.com", "Keller"], check="restore")
    return S


def read_response(ctype, raw):
    if "event-stream" in ctype:
        txt = ""
        for line in raw.decode().splitlines():
            if line.startswith("data:") and "[DONE]" not in line:
                for ch in json.loads(line[5:]).get("choices", []):
                    txt += (ch.get("delta") or {}).get("content") or ""
        return txt
    msg = json.loads(raw)["choices"][0]["message"]
    out = msg.get("content") or ""
    for tc in msg.get("tool_calls") or []:
        json.loads(tc["function"]["arguments"])  # must stay valid JSON
        out += " " + tc["function"]["arguments"]
    return out


def run_e2e(pii_url):
    cap = Capture()
    port = free_port()
    env = dict(os.environ, PSEUDO_PORT=str(port), PSEUDO_UPSTREAM=f"http://127.0.0.1:{cap.port}",
               PSEUDO_PII_URL=pii_url, PSEUDO_AUDIT="0", PSEUDO_FALLBACK_MODELS="")
    proc = subprocess.Popen([sys.executable, os.path.join(HERE, "..", "..", "apps", "pseudonymization-proxy", "proxy.py")],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    res = []
    try:
        if not wait_http(f"http://127.0.0.1:{port}/health"):
            raise RuntimeError("lokaler Proxy startet nicht")
        for s in e2e_scenarios():
            n0 = len(cap.bodies)
            body = dict(s["body"], model="bench")
            t0 = time.time()
            try:
                _, ctype, raw = post(f"http://127.0.0.1:{port}/v1/chat/completions", body)
            except Exception as e:  # noqa: BLE001
                print(f"  {s['id']:<22} FEHLER {e}")
                res.append(dict(id=s["id"], level=5, cat=s["cat"], ok=False, leaks=s["pii"],
                                fps=[], n_pii=len(s["pii"]), error=str(e), design=s["design"]))
                continue
            dt = time.time() - t0
            if len(cap.bodies) == n0:
                print(f"  {s['id']:<22} nichts beim Upstream angekommen")
                continue
            seen = cap.bodies[-1]
            view = upstream_view(seen)
            leaks = [p for p in s["pii"] if p in view]
            notes = []
            ok = not leaks
            if s["check"] == "consistent":
                phs = [PH_RX.findall(m["content"]) for m in seen["messages"] if m["role"] != "system"]
                flat = [p for ps in phs for p in ps if p.startswith("PERSON")]
                if len(set(flat)) > 2:  # Lea Vogt + Tobias
                    ok = False
                    notes.append("inconsistent placeholders: " + ", ".join(sorted(set(flat))))
            if s["check"] == "no_file":
                if any(isinstance(p, dict) and p.get("type") == "file"
                       for m in seen["messages"] if isinstance(m.get("content"), list)
                       for p in m["content"]):
                    ok = False
                    notes.append("file part went out unchanged")
                raw_seen = json.dumps(seen, ensure_ascii=False)
                miss = [x for x in s["expect"] if x not in raw_seen]
                if miss:
                    ok = False
                    notes.append(f"expected content missing: {miss}")
                elif s["expect"]:
                    notes.append("content arrives as text" if "not forwarded" not in s["expect"]
                                 else "blocked with notice")
            if s["check"] == "image_unchanged":
                sent = s["body"]["messages"][0]["content"][1]["image_url"]["url"]
                got = seen["messages"][-1]["content"][1]["image_url"]["url"]
                if sent == got:
                    ok = False
                    leaks = ["<image unchanged>"]
                    notes.append("image passed through unchecked, text in the image would leave")
            if s["check"] == "restore":
                try:
                    out = read_response(ctype, raw)
                except ValueError as e:
                    out, ok = "", False
                    notes.append(f"response broken: {e}")
                left = PH_RX.findall(out)
                miss = [p for p in s["pii"] if p not in out]
                if left or miss:
                    ok = False
                    notes.append(f"reverse mapping incomplete: left over {left}, missing {miss}")
                else:
                    notes.append("reverse mapping ok")
            if leaks and s["design"]:
                notes.append("(expected: " + s["design"] + ")")
            res.append(dict(id=s["id"], level=5, cat=s["cat"], design=s["design"],
                            n_pii=len(s["pii"]), leaks=leaks, fps=[], ok=ok and not leaks,
                            secs=round(dt, 2), notes=notes))
            flag = "ok " if ok and not leaks else ("LECK" if leaks else "FAIL")
            print(f"  {s['id']:<22} {flag} {len(s['pii']) - len([l for l in leaks if l in s['pii']]):>2}/"
                  f"{len(s['pii']):<2} {dt:5.2f}s  "
                  + "; ".join((["leaks: " + ", ".join(repr(x) for x in leaks[:6])] if leaks else []) + notes))
    finally:
        proc.terminate()
        cap.srv.shutdown()
    return res


# ------------------------------------------------------------------ Auswertung

def summary(results):
    rows = []
    for lv in sorted({r["level"] for r in results}):
        rs = [r for r in results if r["level"] == lv]
        n = sum(r["n_pii"] for r in rs)
        leaked = sum(len(r["leaks"]) for r in rs)
        fps = sum(len(r["fps"]) for r in rs)
        rows.append(dict(level=lv, name=LEVELS[lv], cases=len(rs),
                         passed=sum(r["ok"] for r in rs), pii=n, caught=n - leaked,
                         recall=(n - leaked) / n if n else None, fps=fps,
                         secs=round(sum(r.get("secs", 0) for r in rs), 1)))
    return rows


def print_summary(rows):
    print("\nLevel            Cases  passed      PII found      Recall  false alarms  Time")
    for r in rows:
        rec = f"{r['recall'] * 100:5.1f} %" if r["recall"] is not None else "    –  "
        print(f"  {r['level']} {r['name']:<14} {r['cases']:>3}   {r['passed']:>3}/{r['cases']:<3}"
              f"    {r['caught']:>4}/{r['pii']:<4}    {rec}   {r['fps']:>5}     {r['secs']:>5}s")


def write_md(path, rows, results, meta):
    L = [f"# Pseudo-Proxy-Benchmark {meta['date']}", "",
         f"Ziel: `{meta['target']}`, Detektor: `{meta['pii']}`", "",
         "| Level | Cases | passed | PII found | Recall | False alarms |",
         "|---|---|---|---|---|---|"]
    for r in rows:
        rec = f"{r['recall'] * 100:.1f} %" if r["recall"] is not None else "–"
        L.append(f"| {r['level']} {r['name']} | {r['cases']} | {r['passed']} | "
                 f"{r['caught']}/{r['pii']} | {rec} | {r['fps']} |")
    L += ["", "## Individual cases", "", "| Case | Category | Result | Details |", "|---|---|---|---|"]
    for r in results:
        res = "ok" if r["ok"] else ("Leck" if r["leaks"] else "Fehlalarm/Fehler")
        det = []
        if r["leaks"]:
            det.append("leckt " + ", ".join(f"`{x}`" for x in r["leaks"]).replace("\n", "⏎"))
        if r.get("fps"):
            det.append("destroyed " + ", ".join(f"`{x}`" for x in r["fps"]))
        if r.get("roundtrip") is False:
            det.append("reverse mapping differs")
        det += r.get("notes", [])
        if r.get("design") and r["leaks"]:
            det.append(f"*erwartet: {r['design']}*")
        L.append(f"| {r['id']} | {r['cat']} | {res} | {'; '.join(det).replace('|', '\\|')} |")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proxy", help="running proxy, e.g. http://<proxy-host>:9112")
    ap.add_argument("--local", action="store_true", help="start the proxy locally from apps/pseudonymization-proxy/proxy.py")
    ap.add_argument("--pii-url", default="http://127.0.0.1:9111", help="GLiNER service for --local/--e2e")
    ap.add_argument("--e2e", action="store_true", help="also run level 5 (transport paths)")
    ap.add_argument("--only", help="regex on case ids")
    ap.add_argument("--level", type=int, action="append", help="only these level(s)")
    ap.add_argument("-v", "--verbose", action="store_true", help="show the pseudonymized text")
    ap.add_argument("--json")
    ap.add_argument("--md")
    a = ap.parse_args()

    cases = list(C)
    pc = pdf_extract_case()
    if pc:
        cases.append(pc)
    if a.only:
        cases = [c for c in cases if re.search(a.only, c["id"])]
    if a.level:
        cases = [c for c in cases if c["level"] in a.level]
    cases.sort(key=lambda c: (c["level"], c["id"]))

    proc, target = None, a.proxy
    if a.local or not a.proxy:
        port = free_port()
        env = dict(os.environ, PSEUDO_PORT=str(port), PSEUDO_PII_URL=a.pii_url, PSEUDO_AUDIT="0",
                   PSEUDO_UPSTREAM="http://127.0.0.1:9")
        proc = subprocess.Popen([sys.executable, os.path.join(HERE, "..", "..", "apps", "pseudonymization-proxy", "proxy.py")], env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        target = f"http://127.0.0.1:{port}"
        if not wait_http(target + "/health"):
            sys.exit("lokaler Proxy startet nicht")
    target = target.rstrip("/")
    results = []
    try:
        if cases and (not a.level or set(a.level) - {5}):
            print(f"Detection via {target}/pseudonymize, {len(cases)} cases")
            results += run_detect(target, cases, a.verbose)
    finally:
        if proc:
            proc.terminate()
    if a.e2e or (a.level and 5 in a.level):
        print(f"\nTransport paths (local proxy, capture upstream, detector {a.pii_url})")
        results += run_e2e(a.pii_url)

    rows = summary(results)
    print_summary(rows)
    meta = dict(date=time.strftime("%Y-%m-%d %H:%M"), target=a.proxy or "local (apps/pseudonymization-proxy/proxy.py)",
                pii=a.pii_url)
    if a.json:
        with open(a.json, "w") as f:
            json.dump(dict(meta=meta, summary=rows, results=results), f, ensure_ascii=False, indent=1)
    if a.md:
        write_md(a.md, rows, results, meta)


if __name__ == "__main__":
    main()
