# Benchmark for the pseudonymization proxy

54 detection cases in five levels plus 9 end-to-end cases. All data is made up,
nothing goes to OpenRouter and the audit log stays untouched (`/pseudonymize` writes
none, the end-to-end part runs with `PSEUDO_AUDIT=0`). The inputs are German on
purpose: the detector is evaluated on German text.

| Level | Content |
|---|---|
| 0 false alarms | version numbers, order numbers, amounts, legal paragraphs, dates: should stay untouched |
| 1 easy | mail, phone, name, IBAN, IP, credit card in clean prose |
| 2 medium | passwords, PINs, API keys (OpenRouter, GitHub, AWS), address, tax ID, social-security number, ID card, student ID, license plate, date of birth, diagnosis |
| 3 structured | CSV with and without header, JSON, `.env`, YAML, log lines, SQL, Markdown table, vCard, mail thread with headers |
| 4 hard | obfuscated mail, spelled-out numbers, lowercase, names like Koch/Wolf, international names, typos, code, URL tokens, JWT, private key, quasi-identifiers, PDF text after `pdftotext`, 24k-character document |
| 5 transport paths | text parts, tool-call arguments, tool result (CSV), multi-turn consistency, `system` role, **PDF as `file` part**, image, reverse mapping in streams and tool calls |

A case counts as a leak as soon as one of its PII substrings is still in the text the
upstream sees. First and last names are listed separately. For level 5 the raw body is
checked at the upstream, base64 attachments decoded.

## Usage

```bash
# levels 0-4 against a running proxy
./bench.py --proxy http://<proxy-host>:9112

# level 5 on the GPU host (starts ../../apps/pseudonymization-proxy/proxy.py with a capture upstream)
./bench.py --level 5 --pii-url http://127.0.0.1:9111

# without access to the real service: local GLiNER re-implementation, label set estimated, approximation only
./pii-local.py 19111 &
./bench.py --local --pii-url http://127.0.0.1:19111 --e2e

# options: --only REGEX, --level N, -v (show pseudonymized text), --md, --json
```

## Result 2026-11-19

Details: [results-2026-11-19.md](results-2026-11-19.md).

| Level | passed | recall | false alarms |
|---|---|---|---|
| 0 false alarms | 3/5 | – | 6 |
| 1 easy | 8/8 | 100 % | 0 |
| 2 medium | 11/14 | 85.0 % | 0 |
| 3 structured | 6/10 | 89.9 % | 0 |
| 4 hard | 12/17 | 88.5 % | 0 |
| 5 transport paths | 6/9 | 60.0 % | 0 |

Latency: 0.13 to 0.19 s per short text, 6 s for 24k characters.

**What works well:** all standard formats, passwords and API keys inside a sentence, CSV
with header (18/18), JSON, `.env`, YAML, logs, SQL, code, English text, international
names, lowercase, names like "Koch" and "Wolf", the long document across window borders.
Tool calls, tool results and multi-turn are replaced; the reverse mapping works in streams
and tool arguments (valid JSON).

**PDF:** as text (extracted beforehand, also with hyphenation) good, 8/9. As an attachment
(`type: "file"`) it left completely unfiltered on that day, 0/9. **Fixed in the repo since
2026-11-20** (see below); images (`image_url`) still go out unchecked.

**Leaks, by cause:**

1. **Partial names are not followed.** When "Julia Hartmann" is detected, "Hallo Julia",
   "Frau Vogt", `"last_name": "Hartmann"` and `N:Hartmann;Julia` stay. Affects mail thread,
   JSON, vCard and CSV without header (only first names detected there). Biggest lever,
   solvable inside the proxy: re-replace known values and their name parts in the text.
2. **Attachments:** PDF and image parts (see above).
3. **Formats with neither regex nor model label:** license plates, social-security numbers,
   ICD codes (health data, GDPR Art. 9), private keys, tokens in URL parameters,
   spelled-out phone numbers.
4. **`system` is not filtered** (deliberate, `PSEUDO_ROLES`).

**False alarms:** the IP regex eats version numbers (`1.2.3.4`, and via GLiNER also `3.12.4`
and `0.32.15`), the phone regex order numbers (`0815-4711234`); GLiNER also takes EAN and
case numbers. Dates in a mail quote are replaced as `DATE_OF_BIRTH`.

Local re-implementation against the real service: same result at levels 1, 2 and 5, slight
deviations for addresses and social-security numbers (label set).

## Addendum 2026-11-20: attachments

The proxy now converts `file` parts instead of passing them through:

| Attachment | What the upstream gets |
|---|---|
| PDF with text layer | `pdftotext` text, pseudonymized, as `type: "text"` |
| Text files (`text/*`, JSON, CSV, YAML, XML) | content pseudonymized as text |
| PDF without text layer (scan), Word/Excel/binary, URL or `file_id` instead of data, no PDF tool | only a "not forwarded" notice, **fail closed** |

The filename goes through detection too (`Vertrag Julia Hartmann.pdf` →
`Vertrag [PERSON_1].pdf`). New level-5 cases: `5-pdf-filename`, `5-pdf-scan`, `5-pdf-url`,
`5-csv-file-part`, `5-docx-file-part`. Locally (re-implemented detector) 10/14 passed, no
`file` part reached the upstream in any attachment case; the one leak in the PDF cases is
`Seestraße 14`, which the re-implementation misses but the real service catches in
`2-address`. Phone detection was reworked afterwards (parentheses, line breaks) and
deployed 2026-11-23; the bench numbers above predate that.
