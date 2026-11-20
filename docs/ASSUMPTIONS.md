# Assumptions

Assumptions made while building, grouped by area. Code-level assumptions are marked
`# ASSUMPTION:` in the source and mirrored here.

## General

- A-001: The app runs for a single analyst on one machine. There is no authentication or
  multi-user isolation (out of scope for the brief).
- A-002: Sample documents and synthetic tickets are fictional or public. No real sensitive data
  is committed to the repo.

## Backend

- A-101: Python 3.12 is the target runtime for local development, Docker and CI.
- A-102: The default model tag `qwen3-vl:4b-instruct` is assumed to exist in the Ollama registry.
  It is verified in M2, and the final choice goes in DECISIONS.md.
  (`backend/app/config.py`, `# ASSUMPTION:`)
- A-103: "Model ready" means Ollama's `GET /api/tags` lists the configured model. It does not
  check that the model loads into memory; the first real call may still be slow while it loads.
- A-104: Logs contain metadata only (IDs, stages, durations, error codes). Document content and
  model outputs are never logged, which is a deliberate choice for sensitive data. The trade-off
  is that debugging relies on stored results rather than log lines.
- A-105: Uploaded filenames are not logged either. They can contain personal data (for example
  a name or NRIC in the filename). Logs carry the error code and, from M3, the generated
  document ID.
- A-106: A file must *start* with `%PDF-` to be accepted (see DECISIONS D-015). A genuine PDF
  with leading junk bytes is rejected as `UNSUPPORTED_TYPE`. (`validation.py`, `# ASSUMPTION:`)
- A-107: "Password-protected" means a password is needed to *open* the file. PDFs encrypted
  only with an owner password (permission flags such as "no printing") open without one and
  are accepted. (`validation.py`, `# ASSUMPTION:`)
- A-108: "Smaller than 100x100 px" (decorative images) is read as *either* dimension under
  100 px, which also catches thin banners and rules.
- A-109: A blank page (no text, images or drawings) never needs visual analysis, even though
  its text layer is under 50 characters. Rule (c), "likely scanned", applies only to pages
  that have some content (see DECISIONS D-014).
- A-110: Lower-case NRIC/FIN values are masked too, because OCR and models do not always keep
  case. (`pii.py`, `# ASSUMPTION:`)
- A-111: Upload size is checked on the complete bytes in M1. In M3 the upload endpoint will
  enforce `MAX_FILE_MB` while streaming, so an oversized upload is never fully buffered.

## Frontend

- A-201: Node 24 LTS (npm 11) is the frontend toolchain (see DECISIONS D-001).
- A-202: In development the backend runs on `127.0.0.1:8000` (uvicorn's default IPv4 bind).
  Vite proxies `/api` there, which can be overridden with `VITE_API_PROXY_TARGET`. The target
  is `127.0.0.1` rather than `localhost` on purpose: on the author's Windows machine `localhost`
  resolved to IPv6 `::1` first, and because uvicorn listens only on IPv4, proxied requests hung.
  For the same reason, the setup scripts tell users to open `http://127.0.0.1:8000`.
- A-203: The analyst uses a current evergreen browser (ES2022 support).

## CI / Docker

- _(added in M5)_

## Known limitations

- L-001: PyMuPDF is licensed AGPL-3.0. That is acceptable for this open-source take-home, but
  an agency deploying this system would need to publish its source under AGPL, buy an Artifex
  commercial licence, or swap PDF processing to permissively licensed libraries
  (pypdfium2 + pdfplumber). See DECISIONS D-012.
- L-002: The prompt-injection scanner is a heuristic regex list. It cannot catch every
  phrasing, other languages, or instructions split across pages. It is one layer of defence,
  not the main one (DECISIONS D-017).
- L-003: The visual-detection heuristics (D-014) are tuned on synthetic fixtures. Unusual
  layouts can be misjudged: for example, a dense form made of many boxes may be flagged as a
  drawing, and a chart drawn as a single path with fewer than 5 items may be missed.
