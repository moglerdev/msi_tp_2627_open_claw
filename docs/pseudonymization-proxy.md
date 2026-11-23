# Pseudonymization proxy and PII filter

Two small services next to the model server keep personal data away from external LLM
providers (e.g. OpenRouter).

| Service | Port | What it does |
|---|---|---|
| PII filter | 9111 | GLiNER2 (`fastino/gliner2-privacy-filter-PII-multi`, 205M, CPU). `POST /redact`, `/extract` |
| Pseudonymization proxy | 9112 | OpenAI-compatible proxy in front of the upstream. Replaces PII with placeholders and maps them back in the answer |

Redacting a *response* (PII filter alone) is too late: the upstream has already seen the
original text. The proxy sits in front of the upstream and substitutes reversibly.

## Flow per request

1. Messages with role `user`, `assistant`, `tool` (including tool-call arguments) go through
   the PII filter plus regexes for mail, IBAN, phone, IP and credit card. `system` is skipped
   by default (it is bot config and ~27k tokens).
2. Originals become `[PERSON_1]`, `[EMAIL_1]`, … The same original always gets the same
   placeholder, numbered by first occurrence, so an unchanged history keeps the same text and
   the upstream's prefix cache stays valid.
3. The request is forwarded; `Authorization` and the attribution headers are passed through.
4. The answer is mapped back (content, reasoning, tool-call arguments, also when streaming;
   a placeholder cut at a chunk boundary is held back until complete).

PDFs and text files sent as `file` parts are extracted (`pdftotext`) and pseudonymized.
Anything that can't be checked (scans, Word files, URLs) is replaced by a notice
(fail closed). **Images are not filtered yet.**

## Design decisions

- **Fail closed.** If the PII filter is down the proxy answers 503 instead of forwarding
  unfiltered text.
- **The upstream's own fallback chain would defeat it.** An agent falling back to another
  model on 4xx/5xx would send plain text. The proxy therefore tries its own fallback models
  and finally answers HTTP 200 with a warning text, never an error code.
- **Models refuse placeholders without a hint.** Once something was replaced, the proxy
  appends a fixed paragraph to the system message ("treat placeholders like real values,
  copy them verbatim"). That removed all refusals in testing.
- **Audit log** keeps what the upstream saw (pseudonymized) and the answer, never the
  mapping. 30 days, mode 0600. The log is still sensitive: values the detector missed are
  in it in clear text, which is the point of the audit. `audit.py report` re-runs the
  detector at a lower threshold to list suspected leaks.

## Measured detection quality

54 recognition cases plus 9 end-to-end cases (`pseudo-bench`): recall easy 100 %,
medium 85 %, structured 90 %, hard 88.5 %. Known gaps:

- Partial names aren't followed ("Julia Hartmann" replaced, later "Hallo Julia" kept;
  `last_name` fields in JSON; vCard `N:` lines).
- Images are not filtered.
- False positives: the IP regex catches version numbers, the phone regex order numbers.
- An unlisted category lands on the nearest label (a matriculation number came back as
  `POSTAL_CODE`).

## Privacy caveats

The proxy reduces what leaves the network; it doesn't make it zero. Context that the
detector doesn't recognise as PII (free-form descriptions) is still sent. For data that
must never leave, use the local model.

## Source

- Proxy, audit tool, start script: [`apps/pseudonymization-proxy/`](../apps/pseudonymization-proxy/)
  (`proxy.py`, `audit.py`, `start.sh`; debug UI in `ui/`)
- PII detector service and Docling RAG: [`apps/rag-service/`](../apps/rag-service/)
- Benchmark and results: [`benchmarks/pseudonymization/`](../benchmarks/pseudonymization/)

The sources were translated to English. The benchmark inputs stay German on purpose.
