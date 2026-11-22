# CLAUDE.md — Project Spec: HTX Document Analyst

> **Read this whole file before starting any task.** It is the single source of truth for this project.
> If a request in chat conflicts with this spec, point out the conflict and ask before proceeding.
> Record every non-obvious design decision in `docs/DECISIONS.md` and every assumption in `docs/ASSUMPTIONS.md`.
> The human author writes the README from these two files, so keep them current.

---

## 1. Context

This is a take-home technical test for an AI Software Engineer role at HTX (Home Team Science and Technology Agency, Singapore). Assessors evaluate the ability to **design, implement, explain and justify** a solution. Code quality, comments and documented reasoning matter as much as features.

### Hard requirements from the brief (all must be met)

- [ ] Public Git repo. `backend/` and `frontend/` directories.
- [ ] Backend: RESTful API in Python (FastAPI). AI/LLM pipeline (no fine-tuning/training). Handles unsupported, invalid and harmful documents (incl. adversarial content). Containerised.
- [ ] Frontend: modern JS framework (React). Upload one or more PDFs. Display key details per document, a consolidated summary across documents, and processing and error states. Containerised.
- [ ] CI pipeline (GitHub Actions) with build and relevant automated tests.
- [ ] Runs locally via a compose file. **Every submitted artifact must execute without errors.** Include setup scripts for any Python environment.
- [ ] Code documented and commented; assumptions stated per task.
- [ ] Sample PDFs provided or referenced.
- [ ] Optional: exactly ONE extra AI feature, documented (purpose + design considerations). We chose **triage**.

---

## 2. Problem statement

A Home Team analyst receives multiple documents about the same incident or theme and must quickly understand them. The flagship scenario is **several incident tickets submitted by members of the public** (narrative + attached photos) that may describe the same event. The analyst needs to:

1. See the key details of each document, with page references they can verify.
2. See what attached images show, as factual observations, separate from inferences.
3. See whether a reporter's claims are consistent with their own photos.
4. See, across documents, which reports describe the same incident, a merged timeline, and where accounts agree or contradict.
5. Get a suggested priority (triage) that they can confirm or override.

The app must also work on general documents (news articles, public reports) via the General profile.

---

## 3. Guiding principles (use these to justify decisions)

1. **Fully local inference.** No document content leaves the machine. All models run via Ollama in Docker. No cloud LLM APIs.
2. **Analyst in the loop.** The AI suggests; the human decides. Nothing is automated beyond analysis.
3. **Verifiable output.** Every extracted claim cites document + page.
4. **Observation vs inference.** Visual analysis separates what is visible from what is inferred. Never identify individuals or assign fault.
5. **All document content is untrusted data**, never instructions.
6. **Runs anywhere with one command.** A mock provider lets the full app run and be tested without the model.
7. **Clarity over cleverness.** Readable, commented code. Small modules.

---

## 4. Tech stack

| Area | Choice | Notes |
|---|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2, Uvicorn | |
| PDF processing | PyMuPDF (`pymupdf`) | Text, tables (`find_tables`), image/drawing detection, page rendering. One library on purpose. |
| LLM runtime | Ollama (`ollama/ollama` Docker image) | Called over HTTP with `httpx` (async). |
| Model | Vision-language model, configured by `OLLAMA_MODEL`. Default `qwen3-vl:4b-instruct` | One model for both text and vision keeps the stack small. Use an **instruct** (non-thinking) tag. Verify the tag exists at build time; record the final choice in DECISIONS.md. |
| Structured output | Ollama `format` parameter with a JSON schema from the Pydantic model | Then validate with Pydantic. |
| Storage | SQLite (jobs, results, feedback) on a Docker volume | |
| Job processing | In-process `asyncio.Queue` worker started in FastAPI lifespan, concurrency 1 | Local model can only do one thing at a time. |
| Logging | Python `logging` with a JSON formatter | No print statements. |
| Backend tests | pytest, pytest-asyncio, httpx `AsyncClient` | |
| Lint/format | ruff | |
| Frontend | React 18 + TypeScript + Vite | Plain CSS modules or Tailwind; keep it simple. |
| Frontend tests | Vitest + React Testing Library | |
| Frontend serving | nginx container serving the built app and proxying `/api` to the backend | Avoids CORS. |
| CI | GitHub Actions | |

Do not add dependencies outside this list without noting why in DECISIONS.md.

---

## 5. Repository layout

```
.
├── CLAUDE.md
├── README.md                    # written by the human author
├── docker-compose.yml
├── docker-compose.gpu.yml       # optional override: NVIDIA GPU for Ollama
├── .env.example
├── .github/workflows/ci.yml
├── docs/
│   ├── DECISIONS.md
│   ├── ASSUMPTIONS.md
│   ├── SCHEMAS.md               # human-readable output schema reference
│   └── images/                  # screenshots and GIFs for README
├── sample_pdfs/
│   ├── README.md                # source, licence and description of every sample
│   ├── tickets/                 # synthetic incident tickets (generated)
│   ├── general/                 # real public documents
│   └── adversarial/             # test files: injection, encrypted, fake PDF, etc.
├── scripts/
│   ├── setup_backend.sh / setup_backend.ps1   # local Python env setup
│   └── generate_sample_tickets.py             # builds synthetic ticket PDFs
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt / requirements-dev.txt
│   ├── app/
│   │   ├── main.py              # app factory, lifespan, routers
│   │   ├── config.py            # settings from env (pydantic-settings)
│   │   ├── api/                 # route modules
│   │   ├── schemas/             # Pydantic models (API + LLM outputs)
│   │   ├── pipeline/            # validation, extraction, vision, analysis, consolidation, triage
│   │   ├── llm/                 # provider interface, ollama provider, mock provider, prompts/
│   │   ├── security/            # pdf safety checks, injection heuristics, PII masking
│   │   ├── storage/             # sqlite repository
│   │   └── logging_config.py
│   └── tests/
└── frontend/
    ├── Dockerfile
    ├── nginx.conf
    └── src/
```

---

## 6. Processing pipeline

Each job contains 1..N documents and an analysis **profile**. Each document moves through stages independently; one failed document does not fail the job (job status becomes `partial`).

**Job statuses:** `queued`, `processing`, `completed`, `partial`, `failed`
**Document statuses:** `queued`, `validating`, `extracting`, `analysing_visuals`, `analysing`, `completed`, `rejected`, `failed`
Status must be updated in storage at every transition so the frontend can show progress.

### Stage 0: Validation (synchronous, at upload, before the job is accepted)
See section 7. Rejected files return a clear error code per file; valid files in the same upload still proceed.

### Stage 1: Extraction (per page)
For each page, produce a `PageContent` record:
- `text`: plain text from the text layer.
- `tables`: tables found with `page.find_tables()`, converted to markdown.
- `needs_visual_analysis`: true if the page has (a) embedded images that are not decorative, or (b) significant vector drawings (charts are often vectors and are NOT returned by image extraction), or (c) is likely scanned (text layer < 50 characters).
- Decorative filter: ignore images smaller than 100x100 px or under 2% of page area (logos, icons).

**Design decision:** for pages needing visual analysis, render the **whole page** to PNG (`RENDER_DPI`, default 150) and send that, rather than individual extracted images. This catches vector charts and scanned pages and needs one model call per page. Trade-off: small images get less resolution. Record this in DECISIONS.md.

Cap visual pages per document at `MAX_VISUAL_PAGES_PER_DOC` (default 20). Prioritise pages with the largest visual area. Add a warning when the cap is hit.

### Stage 2: Visual analysis
One vision call per selected page. The prompt asks the model to identify each visual element, classify it, and respond by type:

| Type | Output |
|---|---|
| `photo` | Factual description + observations list |
| `chart` | Chart type, axes, key values, trend |
| `table` | Markdown table of the data |
| `diagram` / `map` | Structure and labels |
| `scanned_text` | Transcription |
| `decorative` | Skip |

The **incident** profile uses the evidence-observer prompt: record details relevant to an investigation (scene layout, vehicles by type/colour/damage location, road, weather and lighting, signage, debris, visible timestamps), with `observations`, `possible_inferences` (each with a `basis`) and `information_gaps` as separate lists. The prompt forbids identifying individuals, guessing identity, or assigning fault.

All visual outputs are labelled `ai_generated: true`. If the model refuses or fails on a page, record a warning (`VISUAL_ANALYSIS_FAILED`, page N) and continue.

Visual descriptions are appended to that page's content inside clear delimiters:
`[AI VISUAL DESCRIPTION - page N] ... [/AI VISUAL DESCRIPTION]`

### Stage 3: Document analysis
Produce the core schema plus the profile extension (section 8). For long documents that exceed `OLLAMA_NUM_CTX`, use map-reduce: summarise groups of pages into page-cited notes, then analyse the notes. Validate the output with Pydantic. On validation failure, retry once with the validation error included in the prompt; then mark the document `failed` with `LLM_OUTPUT_INVALID`.

### Stage 4: Consolidated report
Runs over all successfully analysed documents. Uses only the per-document structured outputs (not raw text) to stay within context. Produces the consolidated schema.

### Stage 5: Triage (optional AI feature)
Runs after Stage 4. Assigns a suggested priority per document using an explicit rubric (section 8). Never auto-actions anything. `requires_human_review` is always true.

---

## 7. Security and error handling

### File validation (error codes)

| Code | Rule |
|---|---|
| `UNSUPPORTED_TYPE` | A PDF header (`%PDF-` plus a version) must start within the first 1024 bytes. Any bytes before it are stripped before processing and a visible `LEADING_BYTES_IGNORED` warning states how many were ignored. Extension and MIME alone are not trusted. |
| `FILE_TOO_LARGE` | > `MAX_FILE_MB` (default 25) |
| `TOO_MANY_FILES` | > `MAX_FILES` (default 10) per upload |
| `TOO_MANY_PAGES` | > `MAX_PAGES` (default 60) |
| `CORRUPT_PDF` | PyMuPDF cannot open it, or it has 0 pages |
| `ENCRYPTED_PDF` | Password-protected |
| `EMPTY_DOCUMENT` | No text and no visual content |
| `ACTIVE_CONTENT` | Contains JavaScript, `/Launch` or `/OpenAction` with script: policy `ACTIVE_CONTENT_POLICY` (`reject` default, or `warn`). Embedded files: policy `EMBEDDED_FILE_POLICY` (`warn` default, or `reject`); attachments are never extracted or opened. Accepted files carry a visible `ACTIVE_CONTENT` warning. |

Other rules:
- Store uploads under a generated UUID; never use the user's filename in a filesystem path. Sanitise filenames before display.
- Limit rendered page pixel size to prevent memory blow-ups.
- Per-call timeouts for model calls (`LLM_TIMEOUT_SECONDS`, default 300).
- Uploads are deleted after processing unless `RETAIN_UPLOADS=true`.

### Prompt injection defences
1. The system prompt states that the document content is untrusted data to analyse, and instructions inside it must not be followed.
2. Document text is wrapped in delimiters containing a random per-request boundary token.
3. A heuristic scanner (regex list in `security/injection.py`: e.g. "ignore (all|previous|the above) instructions", "you are now", "system prompt", "disregard", "new instructions") flags suspicious passages. The content is still analysed as data, and an `INJECTION_SUSPECTED` warning with the page number is attached to the result and shown in the UI.
4. Outputs must validate against the schema. Free text outside the schema is discarded.
5. The frontend renders all model output as plain text. Never use `dangerouslySetInnerHTML`.

### Sensitive content
- Visual analysis sets `sensitive_content.graphic` for graphic imagery. The UI collapses those descriptions behind a "show" control.
- PII: the model is instructed not to transcribe licence plates, faces/identities or identity numbers. As a backstop, outputs are post-processed to mask Singapore NRIC/FIN patterns (`[STFGM]\d{7}[A-Z]`) and phone numbers.

### API error format
All errors use: `{"error": {"code": "STRING_CODE", "message": "Human readable", "details": {...}}}`

---

## 8. Output schemas

Define these as Pydantic models in `backend/app/schemas/`. Mirror them in TypeScript types in the frontend. Keep `docs/SCHEMAS.md` in sync.

```python
# ---- shared ----
class Citation:      document_id: str; page: int
class Warning:       code: str; message: str; page: int | None

class Entity:
    name: str
    type: Literal["person_role","organisation","location","date_time","vehicle","object","other"]
    pages: list[int]
    # people are recorded by ROLE ("driver of vehicle A"), not by name, in the incident profile

class NotablePoint:  point: str; page: int

class VisualElement:
    page: int
    type: Literal["photo","chart","table","diagram","map","scanned_text"]
    description: str
    observations: list[str] = []
    possible_inferences: list[{"inference": str, "basis": str}] = []
    information_gaps: list[str] = []
    table_markdown: str | None = None
    sensitive_content: {"graphic": bool, "pii_visible": list[str]}
    ai_generated: Literal[True] = True

# ---- core (every document, every profile) ----
class DocumentAnalysis:
    document_id: str
    filename: str
    page_count: int
    profile: Literal["general","incident","statistical"]
    document_type_guess: str          # e.g. "incident ticket", "news article"
    summary: str                      # 3-5 sentences
    main_topics: list[str]
    key_entities: list[Entity]
    notable_points: list[NotablePoint]
    visual_elements: list[VisualElement]
    warnings: list[Warning]
    incident: IncidentExtension | None = None
    statistical: StatisticalExtension | None = None
    triage: Triage | None = None

# ---- incident profile extension (tickets / incident reports) ----
class IncidentExtension:
    ticket: {"reference_no": str | None, "submitted_at": str | None,
             "category": str, "category_confidence": Literal["low","medium","high"]}
    occurred_at_stated: str | None
    location_stated: str | None
    narrative_summary: str
    parties: list[{"role": str, "description": str}]
    claims: list[{"claim": str, "page": int,
                  "corroboration": Literal["supported","contradicted","not_verifiable"],
                  "note": str}]
    consistency_checks: list[{"check": str,
                              "result": Literal["consistent","inconsistent","unclear"],
                              "details": str, "pages": list[int]}]
    missing_information: list[str]

# ---- statistical profile extension (lowest priority) ----
class StatisticalExtension:
    reporting_period: str | None
    key_figures: list[{"metric": str, "value": str, "page": int}]
    trends: list[{"trend": str, "page": int}]

# ---- consolidated (one per job) ----
class ConsolidatedReport:
    overall_summary: str
    common_themes: list[{"theme": str, "citations": list[Citation]}]
    agreements: list[{"point": str, "citations": list[Citation]}]
    contradictions: list[{"topic": str,
                          "positions": list[{"position": str, "citation": Citation}]}]
    timeline: list[{"time": str, "event": str, "citations": list[Citation]}]
    related_document_groups: list[{"document_ids": list[str], "reason": str}]  # e.g. same incident
    information_gaps: list[str]

# ---- triage (optional AI feature) ----
class Triage:
    suggested_priority: Literal["P1","P2","P3","P4"]
    rationale: str
    triggering_factors: list[{"factor": str, "citation": Citation}]
    confidence: Literal["low","medium","high"]
    requires_human_review: Literal[True] = True
    analyst_override: {"priority": str, "reason": str, "at": datetime} | None = None
```

**Triage rubric** (put in the prompt verbatim; document in DECISIONS.md):
- **P1**: Ongoing danger to life, serious injury or death, weapons, or a suspect at large posing a risk.
- **P2**: Injury reported, a party left the scene, significant property damage, or major contradictions needing follow-up.
- **P3**: Property damage only, no injuries, parties identified.
- **P4**: Informational, duplicate of another report, or insufficient detail to act on.

---

## 9. REST API

All routes are prefixed with `/api`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | `{status, provider, model, model_ready}`. Checks Ollama is reachable and the model is pulled. |
| GET | `/profiles` | Available analysis profiles with descriptions. |
| POST | `/jobs` | Multipart: `files[]`, `profile`. Validates synchronously. Returns `202 {job_id, accepted: [...], rejected: [{filename, code, message}]}`. Returns 400 if all files are rejected. |
| GET | `/jobs/{job_id}` | Job status, per-document status, and results when available (documents, consolidated report). |
| GET | `/jobs/{job_id}/documents/{document_id}/pages/{n}.png` | Rendered page preview, so the analyst can verify a citation. (Should-have.) |
| POST | `/jobs/{job_id}/feedback` | `{target: "document"|"consolidated"|"section", target_id, rating: "up"|"down", comment?}` |
| PUT | `/jobs/{job_id}/documents/{document_id}/triage` | Analyst override `{priority, reason}`. |
| GET | `/feedback/stats` | Counts of ratings and triage agreement rate. (Could-have.) |

FastAPI's auto-generated OpenAPI docs at `/docs` must work.

---

## 10. Frontend

The focus is usability, clarity and correct interaction with the backend.

**Components and features**
- **Model status banner**: polls `/api/health`. Shows "Model is downloading / not ready" clearly if `model_ready` is false.
- **Upload panel**: drag-and-drop plus file picker, multiple files, profile selector (with one-line descriptions), client-side checks (type, size, count) with friendly messages. Rejected files from the server are shown per file with their reason.
- **Job progress**: per-document status stepper using the document statuses. Poll `/api/jobs/{id}` every 2s until finished.
- **Results view** with tabs: **Consolidated report** | one tab per document.
  - Document view: summary, topics (chips), entities (grouped by type), notable points, visual elements (graphic content collapsed by default), incident or statistical sections when present, and warnings in a visible banner.
  - Every citation renders as a clickable `p.N` chip that opens the page preview.
  - Triage badge with rationale; analyst can override with a reason.
  - Thumbs up/down feedback on each major section.
- **States**: idle, uploading, processing, completed, partial (show what succeeded and why others failed), failed, backend unreachable. Never a blank screen.
- AI-generated content is visibly labelled.

---

## 11. Logging and feedback

**Logging**
- JSON logs to stdout. Every log line carries `job_id` and `document_id` where applicable.
- Log stage start/end with duration, model call latency, validation rejections, and security events (`INJECTION_SUSPECTED`, `ACTIVE_CONTENT`) at WARNING level.
- **Never log document content or model outputs.** Metadata only. State this in ASSUMPTIONS.md as a deliberate choice for sensitive data.

**Feedback**
- Stored in SQLite with timestamps.
- Purpose: build an evaluation set for comparing prompt changes, and measure triage agreement. It is not used for training (fine-tuning is out of scope per the brief).

---

## 12. Testing and CI

**Backend tests (pytest; all use the mock provider, never a real model)**
- Validation: each error code, using small fixture PDFs generated in `conftest.py` with PyMuPDF (valid, encrypted, fake `.pdf` that is really text, PDF with JavaScript, too many pages, empty).
- Extraction: text, tables, decorative image filtering, scanned-page detection, vector-drawing detection.
- Injection scanner: positive and negative cases.
- PII masking.
- Schema validation and the retry-then-fail path (mock provider returns invalid output).
- API: upload → poll → results end-to-end with the mock provider; mixed valid and invalid upload; error format.

**Frontend tests (Vitest + RTL)**
- Upload panel client-side validation; results rendering from a fixture response; error and partial states.

**CI (`.github/workflows/ci.yml`), triggered on push and PR**
1. `backend`: set up Python, install deps, `ruff check`, `pytest`.
2. `frontend`: set up Node, `npm ci`, lint, `vitest run`, `npm run build`.
3. `docker`: build both images, `docker compose up` with `LLM_PROVIDER=mock` (Ollama service disabled), wait for `/api/health`, run a smoke test that uploads a sample PDF and polls until `completed`.

---

## 13. Docker and running locally

**Services in `docker-compose.yml`**
- `ollama`: `ollama/ollama`, named volume for models, healthcheck.
- `ollama-init`: one-shot container that runs `ollama pull $OLLAMA_MODEL` against the `ollama` service, then exits.
- `backend`: depends on `ollama` healthy. Volume for `/data` (SQLite + temporary uploads).
- `frontend`: nginx, serves the app on port 8080 (or similar) and proxies `/api` to the backend.

Mock mode must work with **no Ollama at all**, e.g. via a compose profile or `docker-compose.mock.yml`, so assessors without the hardware can still run everything.

`docker-compose.gpu.yml` adds the NVIDIA GPU reservation to `ollama`.

**Environment variables (`.env.example`, all with safe defaults)**
`LLM_PROVIDER` (`ollama`|`mock`), `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_NUM_CTX` (default 16384), `LLM_TIMEOUT_SECONDS`, `MAX_FILES`, `MAX_FILE_MB`, `MAX_PAGES`, `MAX_VISUAL_PAGES_PER_DOC`, `RENDER_DPI`, `ACTIVE_CONTENT_POLICY`, `EMBEDDED_FILE_POLICY`, `RETAIN_UPLOADS`, `LOG_LEVEL`, `DATA_DIR`.

**Local dev without Docker**: `scripts/setup_backend.sh` and `.ps1` create a venv and install requirements. The author develops on Windows with Anaconda; also provide `backend/environment.yml` that installs from `requirements.txt`.

**Mock provider behaviour**: returns deterministic, schema-valid output derived from the input (real filename, real page count, first sentences of text as the summary, a fixed sample visual element), so the UI looks realistic in mock mode.

---

## 14. Sample documents

- `scripts/generate_sample_tickets.py` builds 3–4 synthetic incident tickets as PDFs. At least two describe the **same incident from different reporters, with deliberate contradictions** (vehicle count, time, light colour). At least one has a narrative-versus-photo inconsistency.
- Images are openly licensed (e.g. Wikimedia Commons), stored in `sample_pdfs/tickets/assets/` with attribution in `sample_pdfs/README.md`. Ask the author to supply or approve the images; do not download images without confirmation.
- All synthetic content is fictional and marked "SYNTHETIC SAMPLE" in the PDF footer.
- `sample_pdfs/general/`: 2–3 real public documents (author supplies them; list the source URL and licence).
- `sample_pdfs/adversarial/`: a prompt-injection PDF, a fake PDF, an encrypted PDF, a PDF with JavaScript (generated by script).

---

## 15. Conventions

- **Python**: type hints everywhere, Google-style docstrings on public functions, a short header comment in each module explaining its role, ruff-clean. Comment *why*, not just *what*. Mark assumptions in code with `# ASSUMPTION:` and mirror them in ASSUMPTIONS.md.
- **TypeScript**: strict mode, no `any` without a comment explaining it.
- **Prompts** live in `backend/app/llm/prompts/` as separate files, never inline strings scattered through code.
- **Commits**: small, conventional-commit style (`feat:`, `fix:`, `test:`, `docs:`, `ci:`).
- Never commit models, uploads, `.env`, or `node_modules`. Keep `.gitignore` current.

---

## 16. Milestones (build in this order)

**After each milestone: stop, summarise what changed, explain how to verify it manually, confirm tests pass, and update DECISIONS.md / ASSUMPTIONS.md. Wait for the author's go-ahead before starting the next milestone.**

| # | Milestone | Priority | Status |
|---|---|---|---|
| M0 | Scaffold repo layout, `.gitignore`, empty FastAPI app with `/api/health`, Vite React app, docs files | Must | Done |
| M1 | Validation + security checks + extraction (no LLM), with tests and adversarial fixtures | Must | Done |
| M2 | LLM provider interface, mock provider, Ollama provider, visual analysis stage | Must | Done |
| M3 | Document analysis (General profile), consolidated report, async job queue, SQLite, full API, logging | Must | Done |
| M4 | Frontend: upload, progress, results, all states | Must | Done |
| M5 | Dockerfiles, compose (normal, mock, GPU), CI workflow green | Must | Done |
| M6 | Incident profile + sample ticket generator | Should | Done |
| M7 | Triage + analyst override + feedback capture | Should | Done (plus weapon fact, D-068) |
| M8 | Page previews, statistical profile, feedback stats | Could | Skipped (D-069). Feedback stats was built in M7; statistical is listed as "coming later" |
| M9 | Polish, clean-clone test run, final docs pass | Must | Done |
