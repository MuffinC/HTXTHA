# README fact sheet

Verified, copy-ready material for the README. Not prose. Every command below was run during M9
(a fresh clone of `main` into an empty folder, Windows 10, Python 3.12.0, Node 24.22.3, Docker
Desktop 29.2.0) unless a row says otherwise. Sources: DECISIONS (D-xxx) and ASSUMPTIONS (A-xxx,
L-xxx).

---

## 1. Run it

### Mock mode (no model, no GPU, runs anywhere)

```bash
docker compose -f docker-compose.mock.yml up --build
```

- Open <http://127.0.0.1:8080>. A "Mock mode" strip says results are generated samples.
- M9 clean clone: build + start until healthy **90 s** (images partly cached); a from-scratch
  `--no-cache --pull` build took 133 s in M5 (D-054).
- Optional: `MOCK_DELAY_SECONDS=2` makes progress visible in demos.
- Stop and remove its volume: `docker compose -f docker-compose.mock.yml down -v`

### Real model with an NVIDIA GPU (Docker)

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build
```

- Open <http://127.0.0.1:8080>. The top bar shows "Model is downloading / not ready" until the
  one-shot `ollama-init` service has pulled `qwen3-vl:4b-instruct` (about 3.3 GB; 119 s on the
  author's connection, D-054). Uploads are blocked until the model is ready.
- Needs an NVIDIA driver and GPU support in Docker (Docker Desktop with WSL 2 on Windows; the
  NVIDIA Container Toolkit on Linux). Quit any native Ollama first.
- Give Docker Desktop's VM at least 12 GB of memory for long runs (A-306).
- **Not re-run in M9** (Docker's Ollama was deliberately not started); last verified in M5
  (D-054): stack start 15 s, smoke test with the real model 33 s cold, incident pair 43 s warm.

### Real model without a GPU (Docker, CPU only)

```bash
docker compose up --build
```

- Same as above without the GPU override. Works, but every model call is far slower. Not timed.

### Local development (no Docker)

Backend, Windows PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass   # only if scripts are blocked
.\scripts\setup_backend.ps1
.\backend\.venv\Scripts\Activate.ps1
cd backend
$env:LLM_PROVIDER="mock"; $env:DATA_DIR="./data"; uvicorn app.main:app --reload
```

Backend, Linux / macOS / Git Bash:

```bash
./scripts/setup_backend.sh
source backend/.venv/bin/activate        # Git Bash: source backend/.venv/Scripts/activate
cd backend
LLM_PROVIDER=mock DATA_DIR=./data uvicorn app.main:app --reload
```

Conda alternative: `conda env create -f backend/environment.yml` then
`conda activate htx-doc-analyst` (not re-run in M9).

- API: <http://127.0.0.1:8000/api/health>, docs at <http://127.0.0.1:8000/api/docs>.
- Use `127.0.0.1`, not `localhost`: `localhost` may resolve to IPv6, where uvicorn does not
  listen (A-202).

Frontend (dev server, proxies `/api` to `http://127.0.0.1:8000`):

```bash
cd frontend
npm ci
npm run dev        # http://localhost:5173
```

Real model with native Ollama instead of Docker:

- Point the backend at it: `OLLAMA_BASE_URL=http://127.0.0.1:11434` and `LLM_PROVIDER=ollama`.
- Run the Ollama server with `OLLAMA_FLASH_ATTENTION=1` and `OLLAMA_KV_CACHE_TYPE=q8_0`, so the
  16k context fits in 8 GB of VRAM (D-023). On Windows: `setx` both, then fully quit Ollama
  (tray icon > Quit) and start it again.

---

## 2. Test it

| What | Command | M9 result |
|---|---|---|
| Backend tests (mock provider only) | `cd backend` then `pytest` | 401 passed, 8 deselected (live tests), about 70 s |
| Backend lint and format | `cd backend` then `ruff check . ../scripts --config pyproject.toml` and `ruff format --check . ../scripts --config pyproject.toml` | clean |
| Live-model tests (opt-in, needs Ollama and the model) | `cd backend` then `pytest -m ollama` | report-only scorecards; see section 5 |
| Frontend lint, types, tests, build | `cd frontend` then `npm ci`, `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` | 35 tests passed; build clean |
| Smoke test against a running stack | `bash scripts/smoke_test.sh http://127.0.0.1:8080 120` | passed, job completed in 2–3 s (mock) |
| Regenerate frontend fixtures after an API change | `cd backend` then `UPDATE_FRONTEND_FIXTURES=1 pytest tests/test_frontend_fixtures.py` | |
| Regenerate sample PDFs | `python scripts/generate_sample_tickets.py` and `python scripts/generate_adversarial_pdfs.py` | tickets byte-identical; `encrypted.pdf` differs by design (random salt) |

**Windows note (frontend tests):** run `npm test` from **PowerShell**. Vitest fails with "failed
to find the current suite" when Node's working directory has a lower-case drive letter
(`c:\...`), which a Git Bash started by VS Code can pass on. In Git Bash, `cd "C:/path/to/frontend"`
(upper-case drive letter) first also works. Two config-level fixes were tried and did not help
(D-071).

**CI** (`.github/workflows/ci.yml`, on every push and PR): backend (ruff, pytest, fixture drift
check), frontend (lint, typecheck, tests, build), then Docker (build both images, start the mock
stack, smoke test through nginx).

**Reliability:** the full backend suite was run 10 times in a row before and after the D-070
fix. Before: 9 of 10 passed (the one failure was a real PII-masking bug, D-070). After: **10 of
10 passed** (401 tests each, 66–91 s per run).

---

## 3. Environment variables

All have safe defaults in `backend/app/config.py`; copy `.env.example` to `.env` to change them.

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `ollama` (local model) or `mock` (deterministic, no model) |
| `OLLAMA_BASE_URL` | `http://ollama:11434` | Compose service name; native Ollama: `http://127.0.0.1:11434` |
| `OLLAMA_MODEL` | `qwen3-vl:4b-instruct` | Vision-language model, used for text and images |
| `OLLAMA_NUM_CTX` | `16384` | Context window; needs flash attention + q8_0 KV on 8 GB GPUs, otherwise use `8192` |
| `LLM_TIMEOUT_SECONDS` | `300` | Per model call |
| `MOCK_DELAY_SECONDS` | `0` | Mock only: pause per call, for demos (0–30) |
| `MAX_FILES` | `10` | Files per upload |
| `MAX_FILE_MB` | `25` | Per file |
| `MAX_PAGES` | `60` | Per file |
| `MAX_VISUAL_PAGES_PER_DOC` | `20` | Pages sent to visual analysis; largest visual area first |
| `RENDER_DPI` | `150` | Page render resolution for visual analysis (36–600) |
| `ACTIVE_CONTENT_POLICY` | `reject` | `reject` or `warn` for JavaScript and launch actions |
| `EMBEDDED_FILE_POLICY` | `warn` | `warn` or `reject` for embedded files (attachments are never extracted or opened) |
| `MASK_PII` | `true` | Mask NRIC/FIN and phone numbers in model output |
| `RETAIN_UPLOADS` | `false` | Keep uploaded PDFs after processing |
| `LOG_LEVEL` | `INFO` | `DEBUG` to `CRITICAL` |
| `DATA_DIR` | `/data` | SQLite database and temporary uploads (fixed to `/data` in Docker) |
| `FRONTEND_PORT` | `8080` | Docker only: host port for the UI, bound to 127.0.0.1 |
| `NGINX_CLIENT_MAX_BODY_SIZE` | `260m` | Docker only: nginx upload limit; must be ≥ `MAX_FILES × MAX_FILE_MB` + about 1 MB |

Ollama **server** settings (not app settings; set on the compose `ollama` service, or in the
environment of a native Ollama): `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`,
`OLLAMA_KEEP_ALIVE=15m`.

---

## 4. Error codes

Every API error uses `{"error": {"code": "...", "message": "...", "details": {...}}}`.

**Upload validation** (per file, in `rejected[]` of `POST /api/jobs`; valid files in the same
upload still proceed):

| Code | Triggered by |
|---|---|
| `UNSUPPORTED_TYPE` | No PDF header (`%PDF-` plus a version) in the first 1024 bytes (extension and MIME are ignored). Leading bytes before a header are stripped with a warning |
| `FILE_TOO_LARGE` | Larger than `MAX_FILE_MB` (25). Also 413 if the whole request exceeds `MAX_FILES × MAX_FILE_MB` + 1 MB |
| `TOO_MANY_PAGES` | More than `MAX_PAGES` (60) |
| `CORRUPT_PDF` | PyMuPDF cannot open it, or it has 0 pages |
| `ENCRYPTED_PDF` | Password-protected |
| `EMPTY_DOCUMENT` | No text, images or drawings on any page |
| `ACTIVE_CONTENT` | JavaScript or a launch action (default `reject`); embedded files only with `EMBEDDED_FILE_POLICY=reject` (default `warn`) |

**Request errors:**

| Code | HTTP | Triggered by |
|---|---|---|
| `TOO_MANY_FILES` | 400 | More than `MAX_FILES` (10) in one upload |
| `NO_VALID_FILES` | 400 | Every file in the upload was rejected |
| `UNSUPPORTED_PROFILE` | 400 | The statistical profile ("coming later") |
| `VALIDATION_ERROR` | 422 | Malformed request; also an override without a priority or a 5+ character reason |
| `NOT_FOUND` / `METHOD_NOT_ALLOWED` | 404 / 405 | Unknown job, document or route |
| `INTERNAL_ERROR` | 500 | Unexpected failure; no internals exposed |

**Processing errors** (on a document or job; one failed document makes the job `partial`):

| Code | Meaning |
|---|---|
| `LLM_OUTPUT_INVALID` | Model output still invalid after one retry with the validation error |
| `LLM_TIMEOUT` | A model call exceeded `LLM_TIMEOUT_SECONDS` |
| `LLM_UNAVAILABLE` | Ollama not reachable or the model not pulled |
| `LLM_REFUSED` | The model refused |
| `INTERRUPTED` | The backend restarted while the job was queued or running |
| `SINGLE_DOCUMENT` | (consolidated report) Only one document was analysed |
| `NO_DOCUMENT_ANALYSED` | (job) No document could be analysed |

**Warnings** (shown in the UI, the document still completes): `INJECTION_SUSPECTED` (per page),
`ACTIVE_CONTENT` (embedded file, or any kind under policy `warn`), `LEADING_BYTES_IGNORED`,
`VISUAL_PAGES_CAPPED`, `TABLE_EXTRACTION_FAILED`, `VISUAL_ANALYSIS_FAILED`, `CITATIONS_REMOVED`,
`CONTENT_TRUNCATED`, `INCIDENT_EXTRACTION_FAILED`.

**Notes** (info level, shown as notes, not warnings): `VISUAL_NOT_DESCRIBED` ("No visual content
was described on page N; check the page if it contains a chart or image.").

---

## 5. Scorecards (live model, `qwen3-vl:4b-instruct`, RTX 3070 8 GB)

**Contradiction scorecard** (two synthetic reports of one incident, four planted
contradictions; D-042, D-060):

| Measure | M3 baseline, general profile (7 runs) | M6, incident profile (5 runs) |
|---|---|---|
| Planted contradictions found (mean, of 4) | 2.7 | **4.0** |
| Traffic light found | 1/7 | **5/5** |
| Vehicle count found | 4/7 | **5/5** |
| Time / weather found | 7/7 / 7/7 | 5/5 / 5/5 |
| False contradictions per run (mean) | 0.9 | **0** |
| Runs with an "absence" contradiction | 2/7 | **0/5** |
| Pair grouped as one incident | 6/7 | **5/5** |
| Report calls them separate incidents | 2/7 | 0/5 |

**Ticket scorecard** (four synthetic tickets; D-059, D-060, D-068):

| Measure | M6 (5 runs) | After the weapon fact (1 run) |
|---|---|---|
| Field extraction | 20/20 every run | 20/20 |
| Weapon field (not mentioned on all 4) | n/a | 4/4 |
| Planted contradictions (6) | 6/6 every run | 6/6 |
| False contradictions | 0 every run | 0 |
| T4 narrative vs photo (weather, lighting) | 2/2 every run | 2/2 |
| Grouping (T1–T3 one incident, T4 separate) | correct 5/5 | correct |

**Triage, live** (five tickets; D-067, D-068): T1 P3, T2 P2, T3 P2, T4 P3, T5 P1 (weapon, rule
floor); group T1–T3 P2.

---

## 6. Timing

| Measurement | Result | Source |
|---|---|---|
| One visual page (150 DPI), warm, flash attention + q8_0 KV, 16k context | chart 2.9 s median, photo 3.9 s median | D-023 (M2) |
| Same, cold (model load included) | chart 12.5 s, photo 14.6 s | D-023 (M2) |
| Same with default server settings at 16k (model spills on 8 GB) | 17–56 s warm, one call 278–300 s | D-023 (M2) |
| Synthetic incident pair (3 pages, 1 photo), upload to completed | 45.8 s native, 43 s Docker GPU | D-054 (M5) |
| Four tickets, incident profile (scorecard) | 77–90 s | D-060 (M6) |
| Five tickets, incident profile, with triage | 174 s (M7); 440 s in the weapon re-run with other GPU apps open (GPU contention, D-072) | D-067, D-068 |
| Mock stack: build + healthy / smoke job | 90 s (M9, partly cached) / 2–3 s | M9 |
| Three real public documents, General profile (NTSB brief 10 pp + two NHTSA notes 15 pp each; 20 visual pages; map-reduce on both NHTSA notes) | **300 s** (first run, `ACTIVE_CONTENT_POLICY=warn`); **338 s** (re-run with default settings) | D-073, D-078 |
| **Clean state** (other GPU apps closed, model 100% in VRAM): one visual page, warm | chart **2.5 s**, photo **4.5 s** (median of 3); cold 13.6 s / 10.9 s | D-072 (M9) |
| **Clean state:** five tickets, incident profile, with triage | **117 s** | D-072 (M9) |

Hardware: NVIDIA RTX 3070 8 GB, Windows 10 (WDDM; the desktop uses about 2.5 GB of VRAM before
Ollama loads). Other GPUs and CPU-only machines will differ a lot (A-114, L-005).

---

## 7. Known limitations

| ID | Limitation |
|---|---|
| L-001 | PyMuPDF is AGPL-3.0; an agency deployment would need to publish source, buy a licence, or swap libraries |
| L-002 | The prompt-injection scanner is a regex heuristic; it misses other phrasings, languages and split instructions |
| L-003 | Visual-detection heuristics are tuned on synthetic fixtures; unusual layouts can be misjudged |
| L-004 | The 4B model can be steered by instructions on the page; this is detected and flagged, not prevented |
| L-005 | Per-page timings only hold on a GPU that fits the whole model; with default server settings an 8 GB card spills |
| L-006 | Visual output quality is a 4B Q4 model's: accurate but sparse photo descriptions, possible misreads |
| L-007 | The model-written overall summary can be inaccurate; the incident count above it is code-generated (mitigated) |
| L-008 | Jobs run one at a time from an in-memory queue; a restart loses queued work |
| L-009 | `/api/docs` loads Swagger assets from a CDN, so it does not render offline (the app itself does) |
| L-010 | The `ollama/ollama` image runs as root inside its container (port not published) |
| L-011 | No gazetteer: different names for the same place do not group (shown as "possibly related" when date and time match) |
| L-012 | Quote grounding uses cue words; unusual wording can lose a fact (never invents a contradiction) |
| L-013 | Narrative-vs-photo checks assume the photo was taken at the time of the incident |
| L-014 | The mock provider's incident extraction is keyword matching tuned to the sample tickets |
| L-015 | A masked contact number appeared as an entity (fixed: placeholder-only entities are dropped) |
| L-016 | Triage asymmetry: injected text cannot lower a priority below the rule floor, but could induce an escalation (deliberate, safety-first) |
| L-017 | Raise grounding checks the quote is on the page, not that it supports the claim (negated weapon quotes now rejected) |
| L-018 | The mock's triage raise is a weapon keyword match; on the sample tickets it now changes nothing |
| L-019 | The 4B model did not raise the knife ticket in M7; now covered by the weapon rule, the model raise remains a rarely firing backstop |
| L-020 | The weapon negation check is a word list; double negatives can flip the value |
| L-021 | No page images: a citation opens a drawer of everything cited on that page, but not the page itself (M8 skipped) |
| L-022 | Stage 1 over-flags masthead banners and shaded text boxes as visual; the empty result is now an info note, not a warning (mitigated) |
| L-023 | Photo "observations" can include facts from the surrounding page text, because the whole page is rendered; cropping to image regions is future work |
| L-024 | Bytes before the PDF header (e.g. NHTSA's multipart-wrapped downloads): now stripped with a warning if the header is within 1024 bytes (resolved) |
| L-025 | Harmless attachments such as Acrobat `.joboptions`: embedded files now default to `warn` (resolved) |
