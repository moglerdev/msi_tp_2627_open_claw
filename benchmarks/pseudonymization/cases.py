"""Test cases for the pseudonymization benchmark.

All persons, numbers and credentials are made up. IBAN and credit card are the
public example/test numbers. The inputs are German on purpose (the detector is
evaluated on German text); only comments and labels are English.

Each case:
  id        unique, prefix = level
  level     1 (easy) .. 5 (formats / transport paths)
  cat       category for the evaluation
  text      input (for the detection cases)
  pii       substrings that must NOT appear at the upstream any more.
            Names are deliberately listed as first and last name separately:
            if one stays, that is a leak.
  keep      substrings that should stay (false-positive check).
  design    optional: justification if a leak is expected under the current
            configuration (SKIP_LABELS, system role ...). Still counts as a
            leak but is reported separately.
"""

C = []


def case(id, level, cat, text, pii, keep=(), design=None):
    C.append(dict(id=id, level=level, cat=cat, text=text, pii=list(pii),
                  keep=list(keep), design=design))


# ------------------------------------------------------------ Level 1: easy
# Standard formats in short, clean prose.

case("1-email", 1, "email",
     "Schreib bitte an julia.hartmann@gmx.de wegen des Termins am Montag.",
     ["julia.hartmann@gmx.de"], ["Termins", "Montag"])
case("1-phone-intl", 1, "phone",
     "Meine Handynummer ist +49 171 2345678, ruf gern nach 18 Uhr an.",
     ["2345678"], ["18 Uhr"])
case("1-phone-de", 1, "phone",
     "Festnetz: 07531 206-0, Fax 07531 206-87.",
     ["07531 206", "206-87"])
case("1-name", 1, "person",
     "Tobias Brenner hat gestern wegen der Rechnung angerufen.",
     ["Tobias", "Brenner"], ["Rechnung"])
case("1-iban", 1, "iban",
     "Bitte überweise den Betrag auf DE89 3704 0044 0532 0130 00.",
     ["DE89 3704 0044 0532 0130 00"], ["Betrag"])
case("1-ip", 1, "ip",
     "Der Server 192.168.17.42 antwortet seit heute Morgen nicht mehr.",
     ["192.168.17.42"], ["Server"])
case("1-cc", 1, "credit_card",
     "Bezahlt wurde mit der Kreditkarte 4111 1111 1111 1111, gültig bis 08/29.",
     ["4111 1111 1111 1111"])
case("1-signature", 1, "mixed",
     "Viele Grüße\nJulia Hartmann\nTel. 0151 98765432\njulia.hartmann@example.org",
     ["Julia", "Hartmann", "98765432", "julia.hartmann@example.org"], ["Viele Grüße"])

# ------------------------------------------------------------ Level 2: medium
# Credentials, German ID numbers, addresses.

case("2-password", 2, "password",
     "Mein Passwort fürs Moodle ist Sommer2024!Konstanz, bitte nicht weitergeben.",
     ["Sommer2024!Konstanz"], ["Moodle"])
case("2-login", 2, "password",
     "Zugang zum Router: Benutzer admin, Passwort Xk7#pQ9$vL2m",
     ["Xk7#pQ9$vL2m"], ["Router"])
case("2-pin", 2, "password",
     "Die PIN meiner EC-Karte ist 4711, die PUK 82736451.",
     ["4711", "82736451"])
case("2-apikey-openrouter", 2, "secret",
     "Hier mein Key: sk-or-v1-3f9a1c0d7e2b4a6f8c1d3e5f7a9b0c2d4e6f8a1b3c5d7e9f",
     ["3f9a1c0d7e2b4a6f8c1d3e5f7a9b0c2d4e6f8a1b3c5d7e9f"])
case("2-apikey-github", 2, "secret",
     "Nimm den Token ghp_R8x2Kq9LmZ4vT7bW1nY6cH3jP0sD5fG8aE2u für das Repo.",
     ["ghp_R8x2Kq9LmZ4vT7bW1nY6cH3jP0sD5fG8aE2u"], ["Repo"])
case("2-apikey-aws", 2, "secret",
     "aws_access_key_id = AKIAIOSFODNN7EXAMPLE\naws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
     ["AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"])
case("2-address", 2, "address",
     "Ich wohne in der Seestraße 14, 78464 Konstanz, dritter Stock.",
     ["Seestraße 14", "78464"], ["dritter Stock"])
case("2-steuer-id", 2, "gov_id",
     "Meine Steuer-ID lautet 12 345 678 903.",
     ["12 345 678 903"])
case("2-svnr", 2, "gov_id",
     "Sozialversicherungsnummer: 65 170839 J 003",
     ["170839"])
case("2-ausweis", 2, "gov_id",
     "Personalausweisnummer L01X00T47, ausgestellt in Konstanz.",
     ["L01X00T47"])
case("2-matrikel", 2, "gov_id",
     "Matrikelnummer 304512, Studiengang Autonome Systeme.",
     ["304512"], ["Autonome Systeme"])
case("2-kfz", 2, "gov_id",
     "Das Auto mit dem Kennzeichen KN-AB 1234 steht falsch.",
     ["KN-AB 1234"])
case("2-birthdate", 2, "date",
     "Lea Vogt, geboren am 15.03.1985 in Singen.",
     ["Lea", "Vogt", "15.03.1985"])
case("2-health", 2, "health",
     "Herr Kaiser ist wegen einer mittelgradigen depressiven Episode (F32.1) krankgeschrieben.",
     ["Kaiser", "F32.1"])

# ------------------------------------------------------------ Level 3: structured
# CSV, JSON, configs, logs: little sentence context for the model.

case("3-csv-header", 3, "csv",
     "Name;E-Mail;Telefon;IBAN;Passwort\n"
     "Julia Hartmann;julia.hartmann@gmx.de;0171 2345678;DE89 3704 0044 0532 0130 00;Sommer2024!\n"
     "Tobias Brenner;t.brenner@web.de;0160 5550123;DE02 1203 0000 0000 2020 51;hunter2\n"
     "Mehmet Yilmaz;myilmaz@outlook.com;0152 7778899;DE12 5001 0517 0648 4898 90;Passw0rt#\n",
     ["Julia", "Hartmann", "Tobias", "Brenner", "Mehmet", "Yilmaz",
      "julia.hartmann@gmx.de", "t.brenner@web.de", "myilmaz@outlook.com",
      "2345678", "5550123", "7778899",
      "DE89 3704", "DE02 1203", "DE12 5001",
      "Sommer2024!", "hunter2", "Passw0rt#"],
     ["Name;E-Mail;Telefon;IBAN;Passwort"])
case("3-csv-noheader", 3, "csv",
     '"Anna","Schäfer","Hauptstraße 3","78462","Konstanz","1990-04-12"\n'
     '"Lukas","Weber","Bodanstraße 22","78462","Konstanz","1988-11-30"\n'
     '"Sophie","Fischer","Am Seerhein 7","78467","Konstanz","2001-01-05"\n',
     ["Anna", "Schäfer", "Lukas", "Weber", "Sophie", "Fischer",
      "Hauptstraße 3", "Bodanstraße 22", "Am Seerhein 7"])
case("3-json", 3, "json",
     '{"user": {"first_name": "Julia", "last_name": "Hartmann", '
     '"email": "julia.hartmann@gmx.de", "phone": "+49 171 2345678", '
     '"password": "Sommer2024!", "iban": "DE89370400440532013000", '
     '"last_login_ip": "10.4.2.17"}}',
     ["Julia", "Hartmann", "julia.hartmann@gmx.de", "2345678", "Sommer2024!",
      "DE89370400440532013000", "10.4.2.17"],
     ['"first_name"', '"email"'])
case("3-env", 3, "config",
     "DB_HOST=db.intern\nDB_USER=app\nDB_PASSWORD=Tr0ub4dor&3\n"
     "SMTP_PASSWORD=correcthorsebatterystaple\n"
     "DATABASE_URL=postgres://admin:S3cret!2024@db.intern:5432/app\n",
     ["Tr0ub4dor&3", "correcthorsebatterystaple", "S3cret!2024"],
     ["DB_HOST", "5432"])
case("3-yaml", 3, "config",
     "mattermost:\n  url: https://chat.example.org\n  token: 8f3k2m9x7q1w5e4r6t8y0u2i3o\n"
     "  admin_email: tobias.brenner@example.org\nsmtp:\n  password: \"Kl4us!Bodensee\"\n",
     ["8f3k2m9x7q1w5e4r6t8y0u2i3o", "tobias.brenner@example.org", "Kl4us!Bodensee"],
     ["mattermost:", "smtp:"])
case("3-log", 3, "log",
     "2026-11-18 12:03:11 INFO login ok user=jhartmann ip=10.4.2.17 mail=julia.hartmann@gmx.de\n"
     "2026-11-18 12:04:52 WARN failed login user=tbrenner ip=84.143.20.199 pw_tried=hunter2\n"
     "2026-11-18 12:05:03 INFO session 9f2c renewed for Mehmet Yilmaz",
     ["jhartmann", "10.4.2.17", "julia.hartmann@gmx.de", "tbrenner",
      "84.143.20.199", "hunter2", "Mehmet", "Yilmaz"],
     ["INFO", "WARN"])
case("3-sql", 3, "code",
     "INSERT INTO kunden (vorname, nachname, email, telefon) VALUES\n"
     "('Lea', 'Vogt', 'lea.vogt@t-online.de', '07531 998877'),\n"
     "('Jonas', 'Keller', 'jonas.keller@gmail.com', '0176 11223344');",
     ["Lea", "Vogt", "lea.vogt@t-online.de", "998877", "Jonas", "Keller",
      "jonas.keller@gmail.com", "11223344"],
     ["INSERT INTO kunden"])
case("3-markdown", 3, "table",
     "| Name | Raum | Durchwahl | Mail |\n|---|---|---|---|\n"
     "| Prof. Dr. Klara Neumann | O-204 | 0753 1206-512 | kneumann@htwg-konstanz.de |\n"
     "| Dr. Felix Braun | F-117 | 0753 1206-433 | fbraun@htwg-konstanz.de |\n",
     ["Klara", "Neumann", "Felix", "Braun", "kneumann@htwg-konstanz.de",
      "fbraun@htwg-konstanz.de", "1206-512", "1206-433"])
case("3-vcard", 3, "vcard",
     "BEGIN:VCARD\nVERSION:3.0\nN:Hartmann;Julia;;;\nFN:Julia Hartmann\n"
     "TEL;TYPE=CELL:+491712345678\nEMAIL:julia.hartmann@gmx.de\n"
     "ADR;TYPE=HOME:;;Seestraße 14;Konstanz;;78464;Germany\nBDAY:1985-03-15\nEND:VCARD",
     ["Hartmann", "Julia", "491712345678", "julia.hartmann@gmx.de",
      "Seestraße 14", "78464"])
case("3-mail-thread", 3, "email_thread",
     "From: Tobias Brenner <t.brenner@web.de>\nTo: Julia Hartmann <julia.hartmann@gmx.de>\n"
     "Cc: lea.vogt@t-online.de\nSubject: Re: Wohnungsübergabe\n\n"
     "Hallo Julia,\npasst Donnerstag? Schlüssel liegt bei Frau Vogt.\n\n"
     "> Am 17.11.2026 schrieb Julia Hartmann:\n> Ich bin unter 0171 2345678 erreichbar.",
     ["Tobias", "Brenner", "t.brenner@web.de", "Julia", "Hartmann",
      "julia.hartmann@gmx.de", "lea.vogt@t-online.de", "Vogt", "2345678"],
     ["Wohnungsübergabe", "Donnerstag"])

# ------------------------------------------------------------ Level 4: hard
# Obfuscated, lowercase, ambiguous, foreign-language, hidden in code.

case("4-email-obfusc", 4, "email",
     "Mail mir an julia punkt hartmann at gmx punkt de oder j.hartmann(at)web(dot)de.",
     ["hartmann at gmx", "j.hartmann(at)web"])
case("4-phone-spaced", 4, "phone",
     "Die Nummer ist null eins sieben eins, zwei drei vier, fünf sechs sieben acht. "
     "Alternativ 0 1 5 1 - 9 8 7 6 5 4 3 2.",
     ["zwei drei vier, fünf sechs sieben acht", "9 8 7 6 5 4 3 2"])
case("4-lowercase", 4, "person",
     "hab grad mit tobias brenner telefoniert, der kennt julia hartmann von früher",
     ["tobias", "brenner", "julia", "hartmann"])
case("4-wordnames", 4, "person",
     "Herr Koch und Frau Wolf treffen sich mit Peter Schmied beim Bäcker.",
     ["Koch", "Wolf", "Peter", "Schmied"], ["Bäcker"])
case("4-intl-names", 4, "person",
     "Im Team sind Aleksandra Wójcik, Mehmet Yılmaz, Nguyễn Văn An und Siobhán O'Sullivan.",
     ["Aleksandra", "Wójcik", "Yılmaz", "Nguyễn", "Siobhán", "O'Sullivan"])
case("4-name-variants", 4, "person",
     "Julia Hartmann hat zugesagt. J. Hartmann bringt die Unterlagen, "
     "Frau Hartmann zahlt die Kaution, und Julia holt den Schlüssel.",
     ["Hartmann", "Julia"])
case("4-typo", 4, "person",
     "Tobias Brener (eigentlich Brenner) hat sich vertippt: tobias.brener@web.de",
     ["Tobias", "Brener", "Brenner", "tobias.brener@web.de"])
case("4-english", 4, "mixed",
     "Please contact Sarah Mitchell at sarah.mitchell@acme-corp.com or +1 (415) 555-0132; "
     "her SSN is 078-05-1120 and she lives at 742 Evergreen Terrace, Springfield.",
     ["Sarah", "Mitchell", "sarah.mitchell@acme-corp.com", "555-0132",
      "078-05-1120", "742 Evergreen Terrace"])
case("4-code", 4, "code",
     'client = Mailer(user="jhartmann", password="Sommer2024!",\n'
     '                api_key="sk-live-51HxQ2eLkdIwHu7ix")\n'
     'client.send(to="tobias.brenner@example.org", cc=["Lea Vogt <lea@vogt.name>"])',
     ["jhartmann", "Sommer2024!", "sk-live-51HxQ2eLkdIwHu7ix",
      "tobias.brenner@example.org", "Lea", "Vogt", "lea@vogt.name"],
     ["client.send"])
case("4-url-token", 4, "secret",
     "Der Freigabelink: https://cloud.example.org/s/aB3dE7fG9hJ?token=Zx81Qm4Lw0Pk "
     "und der Reset-Link https://portal.example.org/reset?u=jhartmann&k=7f3a9c1e5b",
     ["Zx81Qm4Lw0Pk", "jhartmann", "7f3a9c1e5b"])
case("4-jwt", 4, "secret",
     "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJqaGFydG1hbm4ifQ.4pcPyMD09olPSyXnrXCjTwXyr4BsezdI1AVTmud2fU4",
     ["eyJzdWIiOiJqaGFydG1hbm4ifQ", "4pcPyMD09olPSyXnrXCjTwXyr4BsezdI1AVTmud2fU4"])
case("4-privkey", 4, "secret",
     "-----BEGIN OPENSSH PRIVATE KEY-----\n"
     "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW\n"
     "QyNTUxOQAAACDx3R7aHq0sT9mYfZk2vP8LwZ3rN6cJ1uQ5yE4oK7bVmgAAAJhG8w0XRvMN\n"
     "-----END OPENSSH PRIVATE KEY-----",
     ["b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW",
      "QyNTUxOQAAACDx3R7aHq0sT9mYfZk2vP8LwZ3rN6cJ1uQ5yE4oK7bVmgAAAJhG8w0XRvMN"])
case("4-iban-nospace", 4, "iban",
     "iban: de89370400440532013000, bic COBADEFFXXX, kontoinhaber j. hartmann",
     ["de89370400440532013000", "hartmann"])
case("4-quasi", 4, "quasi_identifier",
     "Die Leiterin des Studierendensekretariats der HTWG, die im März ihr drittes Kind "
     "bekommen hat und im Paradies wohnt, hat sich krankgemeldet.",
     ["Leiterin des Studierendensekretariats"],
     design="quasi-identifier without names, not a detection target of the model")
case("4-pdf-extracted", 4, "pdf_text",
     # this is what pdftotext -layout looks like with hyphenation and columns
     "Mietvertrag                                    Seite 1/3\n\n"
     "Zwischen  Frau  Julia  Hart-\nmann, wohnhaft Seestra-\nße 14, 78464 Konstanz\n"
     "(Mieterin) und Herrn Tobias Bren-     Tel.: 0171 /\nner (Vermieter)            "
     "2345678\n\nIBAN des Vermieters: DE02 1203 0000\n0000 2020 51",
     ["Julia", "Hart-\nmann", "Seestra-\nße 14", "Tobias", "Bren-",
      "2345678", "DE02 1203 0000", "0000 2020 51"])


# ------------------------------------------------------------ long texts
# One document spanning the 2000-character windows of the PII service.

_FILLER = [
    "Die Sitzung begann pünktlich mit einem Rückblick auf das letzte Semester.",
    "Anschließend wurde der Stand der Laborausstattung besprochen.",
    "Mehrere Punkte zur Raumplanung wurden auf die nächste Sitzung vertagt.",
    "Die Ergebnisse der Evaluation lagen im erwarteten Bereich.",
    "Es wurde vereinbart, die Unterlagen bis Ende des Monats zu überarbeiten.",
    "Zum Budget gab es keine Einwände aus dem Gremium.",
]


def _long_doc():
    inserts = [
        "Protokoll geführt von Klara Neumann (kneumann@htwg-konstanz.de).",
        "Rückfragen bitte an Tobias Brenner unter 0171 2345678.",
        "Die Kaution wird auf DE89 3704 0044 0532 0130 00 überwiesen.",
        "Herr Mehmet Yilmaz hat sein Passwort Sommer2024! im Chat gepostet.",
        "Die neue Hilfskraft heißt Lea Vogt und wohnt in der Seestraße 14.",
        "Das Protokoll wurde an julia.hartmann@gmx.de verschickt.",
    ]
    out, i, k = [], 0, 0
    # insertion positions roughly at the window borders (2000, 3700, 5400, ...)
    targets = [1950, 3680, 5390, 9000, 14000, 21500]
    while k < len(inserts) or len("".join(out)) < 24000:
        cur = len(" ".join(out))
        if k < len(inserts) and cur >= targets[k]:
            out.append(inserts[k])
            k += 1
        else:
            out.append(_FILLER[i % len(_FILLER)])
            i += 1
    return " ".join(out)


case("4-long-24k", 4, "long_doc", _long_doc(),
     ["Klara", "Neumann", "kneumann@htwg-konstanz.de", "Tobias", "Brenner",
      "2345678", "DE89 3704", "Mehmet", "Yilmaz", "Sommer2024!", "Lea", "Vogt",
      "Seestraße 14", "julia.hartmann@gmx.de"])


# ------------------------------------------------------------ False alarms
# No PII in here. Everything in keep should reach the upstream unchanged.

case("0-fp-versions", 0, "false_positive",
     "Wir nutzen Python 3.12.4, Ollama 0.32.15 und Firmware 1.2.3.4 auf Port 8080.",
     [], ["3.12.4", "0.32.15", "1.2.3.4", "8080"])
case("0-fp-numbers", 0, "false_positive",
     "Bestellnummer 0815-4711234, Rechnungsbetrag 1.234,56 €, Artikel 4006381333931, "
     "Aktenzeichen 2 O 345/24.",
     [], ["0815-4711234", "1.234,56", "4006381333931", "2 O 345/24"])
case("0-fp-tech", 0, "false_positive",
     "Das Modell Qwen3.8-27B läuft auf gfx1151 mit 96 GiB VRAM, Prefill 361 tok/s.",
     [], ["Qwen3.8-27B", "gfx1151", "96 GiB", "361 tok/s"])
case("0-fp-public", 0, "false_positive",
     "Laut § 823 BGB und Art. 9 DSGVO; die HTWG Konstanz liegt am Bodensee.",
     [], ["§ 823 BGB", "Art. 9 DSGVO", "Bodensee"])
case("0-fp-dates", 0, "false_positive",
     "Abgabe am 2026-12-01 um 23:59, Klausur am 14.02.2027.",
     [], ["2026-12-01", "23:59", "14.02.2027"])


# ------------------------------------------------------------ Level 5: transport paths
# Not measured via /pseudonymize but end to end through a locally started
# proxy with a capture upstream (bench.py --e2e). Defined there because they
# need request bodies instead of texts.
