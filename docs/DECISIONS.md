# Design decisions

Non-obvious design decisions, with the alternatives considered and the reason for each choice.
The README's "Key design decisions" table is drawn from this file.

Format: **Decision**, *Context*, **Alternatives**, **Why**, **Milestone**.

---

## D-001 Pin Node 24 LTS (npm 11) for the frontend toolchain

- **Context:** With Node 22.13 / npm 10.9.2, `npm install` crashed with
  `TypeError: Cannot read properties of null (reading 'edgesOut')` in arborist's `#loadPeerSet`.
  The cause: `vitest@4.1.12` declares an optional peer `@vitest/browser-webdriverio@^4.1.11`, but
  4.1.12 of that package was never published. npm 10.9's arborist crashes on that conflict
  instead of reporting `ERESOLVE`.
- **Alternatives:** stay on Vitest 3.2 (its tree carries a critical `tinypool` advisory and a
  moderate `@vitest/mocker` advisory); `--legacy-peer-deps` via `.npmrc` (hides real peer
  problems for every package); pin an older Vitest 4.1.x (still inside the advisory range).
- **Why:** Node 24 is the current LTS and bundles npm 11, which resolves the tree correctly.
  This keeps `vitest ~4.1.12` (outside the advisory range) and gives a clean `npm audit`.
- **How it is enforced:** `frontend/package.json` `engines.node` is `>=24 <25`;
  `frontend/.nvmrc` is `24`. The frontend Dockerfile (M5) uses a `node:24` build image and the
  CI workflow (M5) uses `actions/setup-node` with `node-version: 24`.
- **Milestone:** M0

## D-002 Approve esbuild's install script explicitly

- **Context:** npm 11 does not run dependency install scripts unless a package is approved under
  `allowScripts` in `package.json`. esbuild (pulled in by Vite) has a postinstall that verifies
  its platform binary.
- **Alternatives:** leave it unapproved (the build still works because the binary comes from an
  optional dependency, but every install prints a warning); allow all scripts globally.
- **Why:** an explicit, version-pinned allow-list (`"esbuild@0.28.2": true`) keeps installs
  deterministic and quiet while still blocking scripts from any other package. Revisit the entry
  when esbuild is upgraded.
- **Milestone:** M0

## D-003 Frontend toolchain versions: newest set known to work together, not newest available

- **Context:** At build time the newest releases were Vite 8, TypeScript 7 (native port) and
  ESLint 10.
- **Choice:** React 18.3.1 (per spec), Vite 7.3, `@vitejs/plugin-react` 5.2, TypeScript 5.9,
  ESLint 9.39 + typescript-eslint 8, Vitest 4.1.12, jsdom 26.
- **Why:** the brief requires that every artifact runs without errors. typescript-eslint
  officially supports TypeScript 5.x, and this set of major versions is mutually compatible.
  The newest majors add upgrade risk without adding anything this project needs. Versions use
  `~` ranges with a committed `package-lock.json`, so `npm ci` reproduces the exact tree.
- **Milestone:** M0

## D-004 Vite app scaffolded by hand rather than `npm create vite`

- **Why:** the current template targets React 19 and the newest toolchain. The spec requires
  React 18, so writing the small set of config files by hand avoids then downgrading every
  generated dependency.
- **Milestone:** M0

## D-005 `/api/health` always returns HTTP 200 with `status: ok | degraded`

- **Context:** on first start-up Ollama may still be booting or downloading the model, which can
  take many minutes.
- **Alternatives:** return 503 when the model is not ready.
- **Why:** the frontend polls this endpoint to show a "model downloading / not ready" banner, and
  the Docker healthcheck only needs to know that the backend process is up. A 200 with
  `model_ready: false` means "backend alive, model not ready", which is different from "backend
  unreachable". In mock mode `model_ready` is always true. The check calls Ollama's
  `GET /api/tags` with a 3-second timeout. It moves behind the LLM provider interface in M2.
- **Milestone:** M0

## D-006 API docs served under `/api/docs`

- **Why:** the spec prefixes every route with `/api`, and in production nginx proxies only `/api`
  to the backend. Serving `/docs` and `/openapi.json` under `/api` means the interactive docs
  work both through the frontend origin (port 8080) and directly on the backend.
- **Milestone:** M0

## D-007 JSON logging with the standard library only

- **Alternatives:** `python-json-logger`, `structlog`.
- **Why:** a ~30-line `logging.Formatter` covers the need (one JSON object per line plus
  `job_id` / `document_id` / `stage` / `duration_ms` context fields passed through `extra`)
  without adding a dependency outside the approved stack. Uvicorn's loggers are routed through
  the same handler so all output is JSON.
- **Milestone:** M0

## D-008 App factory (`create_app(settings)`) with per-app settings

- **Why:** tests build isolated app instances with their own settings (mock provider, temp data
  dir) without editing environment variables or global caches. Production uses the module-level
  `app = create_app()`, which reads settings from the environment through `pydantic-settings`.
- **Milestone:** M0

## D-009 Exact pins for Python dependencies; tool config in `backend/pyproject.toml`

- **Why:** `requirements.txt` / `requirements-dev.txt` pin exact versions for reproducible Docker
  and CI builds. `pyproject.toml` holds only ruff and pytest settings; it is not used for
  packaging. Ruff enables the `S` (bandit) security rules alongside the usual style and bug rules.
  `pydantic-settings` is used for `config.py`, as named in the spec's layout.
- **Milestone:** M0

## D-010 ESLint rule bans `dangerouslySetInnerHTML`

- **Why:** the spec requires all model output to be rendered as plain text (prompt-injection
  defence #5). A lint error enforces this in CI instead of relying on code review.
- **Milestone:** M0

## D-011 LF line endings forced for shell scripts and Docker files

- **Why:** the author develops on Windows with `core.autocrlf`. A CRLF `.sh` file or `Dockerfile`
  fails inside Linux containers and CI, so `.gitattributes` forces `eol=lf` for `*.sh`,
  `Dockerfile` and `*.conf`.
- **Milestone:** M0

## D-012 Accept PyMuPDF despite its AGPL-3.0 licence

- **Context:** PyMuPDF (and the MuPDF library under it) is dual-licensed: AGPL-3.0, or a
  commercial licence from Artifex. AGPL is a strong copyleft licence. Anyone who distributes the
  software, *or lets users interact with it over a network*, must make the complete
  corresponding source of the combined application available under AGPL.
- **Why we accept it here:** one library covers every PDF need in the pipeline: the text layer,
  table detection (`find_tables`), image and vector-drawing inspection, encryption and
  active-content checks, page rendering to PNG, and generating test fixtures. Fewer
  dependencies means a smaller attack surface, a single parsing model (the same parser validates
  and extracts, so they cannot disagree about a file), and less code. This repository is public
  and open source, so the AGPL terms are satisfied for the take-home.
- **Deployment implication for a government agency:** an internal HTX deployment would either
  (a) need to keep the full application source available to its users under AGPL, which may
  conflict with policy on internal or security-sensitive systems, or (b) need a commercial
  MuPDF licence from Artifex. Legal or procurement review would be needed before production use.
- **Permissive alternative:** **pypdfium2** (Apache-2.0 / BSD-3, built on Google's PDFium) for
  opening, encryption detection, rendering and the basic text layer, plus **pdfplumber** (MIT)
  for tables and vector-object (lines, rects, curves) inspection. Cost of switching: two
  libraries instead of one, slower table extraction, and active-content detection reimplemented
  over the raw object tree. To keep a swap contained, PyMuPDF is imported only in
  `app/pipeline/pdf_utils.py`, `app/pipeline/validation.py`, `app/pipeline/extraction.py`,
  `app/security/pdf_safety.py` and the test fixture builders (`tests/pdf_factory.py`).
- **Milestone:** M1

## D-013 Render the whole page for visual analysis, not extracted images

- **Context:** visual content in PDFs comes in three forms: embedded raster images (photos,
  scans), **vector drawings** (most charts and diagrams exported from Excel, matplotlib or
  PowerPoint), and scanned pages.
- **Alternatives:** send each extracted embedded image to the vision model.
- **Why:** image extraction returns nothing for vector charts. The `vector_chart.pdf` sample has
  12 drawing paths and zero images, and `test_vector_chart_has_no_embedded_images` pins that
  down. Rendering the page captures all three forms in one model call per page, and keeps the
  chart's surrounding axis labels, caption and legend, which are text and would be lost from a
  cropped image.
- **Trade-off:** a small photo on a page gets fewer pixels than if it were sent alone. Pages
  are rendered at `RENDER_DPI` (150) with a hard cap of 4 MP (`MAX_RENDER_PIXELS`), computed
  *before* rendering so a hostile 5000 × 5000 pt page cannot allocate a 100 MP pixmap.
- **Milestone:** M1 (detection and rendering), M2 (model call)

## D-014 Heuristics for "needs visual analysis"

All thresholds are named constants at the top of `app/pipeline/extraction.py`. Each one is
covered by a test, and the key ones were mutation-checked: disabling each made a specific test
fail.

- **Decorative images:** ignored if either pixel dimension is under 100 px, or the visible
  on-page area is under 2% of the page (spec). Off-page parts of an image are clipped before
  measuring.
- **Significant vector drawings:** `Page.get_drawings()` → drop page-sized backgrounds
  (≥ 90% of page) and **any path touching a detected data table** → cluster nearby paths with
  `Page.cluster_drawings()` → a cluster counts if it has ≥ 5 path items and ≥ 2% page area.
  Clustering stops scattered layout lines (header/footer rules, a border box, link
  underlines) from adding up into a false "chart".
- **Table rules vs charts:** `find_tables()` reports a table bbox narrower than its drawn grid,
  so drawings are excluded when they *intersect* the table bbox (plus 8 pt), not when they are
  contained in it. A ruled table is thus not mistaken for a chart.
- **Charts mistaken for tables:** `find_tables()` reports a chart on a full grid with data
  labels as a table once about 19% of its cells contain text. A "table" with fewer than 50% of
  its cells filled is therefore treated as a grid, not a table, so it is not emitted as
  markdown and its paths stay eligible as a chart. The test fixture is a scatter chart; a line
  or bar series breaks up the grid enough that `find_tables` does not misfire.
- **Likely scanned:** under 50 non-whitespace characters **and** either the largest image
  covers ≥ 50% of the page, or the page has content that rules (a) and (b) did not explain. The
  "unexplained" condition was added after a test showed a chart with a short caption also being
  labelled "scanned", which was the wrong label and inflated its rank to 1.0. Blank pages are
  never flagged, since sending them would waste a model call.
- **Cap:** pages that need visual analysis are ranked by visual area ratio (scanned = 1.0;
  ties go to the earlier page) and the top `MAX_VISUAL_PAGES_PER_DOC` are selected. A
  `VISUAL_PAGES_CAPPED` warning lists the skipped pages. `needs_visual_analysis` keeps the raw
  detection result and `selected_for_visual_analysis` holds the selection, so the UI can explain
  both.
- **Milestone:** M1

## D-015 Validation order and strictness

- **Order:** size → magic bytes → parse → password → page count → active content → emptiness.
  Cheapest checks run first, and no PDF parsing happens until the size and header checks pass.
- **Strict header:** the file must *start* with `%PDF-`. Viewers tolerate junk before the
  header, but strictness rejects polyglot files (for example a file that is both valid HTML
  and a valid PDF) at no cost to genuine PDFs.
- **Extension and MIME type ignored:** a real PDF named `notes.txt` is accepted, and a text
  file named `.pdf` is rejected (tested).
- **One parser:** validation and extraction use the same PyMuPDF parser, so a file cannot pass
  validation under one interpretation and be extracted under another.
- **`TOO_MANY_FILES` is request-level** (`check_file_count` raises `ApiError`, HTTP 400). It
  has no single file to attach to. All other codes are per file, so valid files in the same
  upload still proceed.
- **Milestone:** M1

## D-016 Active-content detection by scanning object dictionaries

- **Approach:** walk every xref and regex-match `/JS`, `/JavaScript`, `/Launch` and
  `/EmbeddedFile(s)` in each object's **dictionary** (`xref_object`), plus
  `embfile_count() > 0`.
- **Why dictionaries only:** stream bodies (page content) can legitimately contain the bytes
  "/JS" as text. Keys in dictionaries are where actions actually live.
- **`/OpenAction` handling:** the spec says "/OpenAction *with script*". A benign OpenAction
  ("open at page 1, fit width") is not flagged (`goto_open_action_pdf` test), while one pointing
  to a JavaScript action is caught through `/JS`.
- **Scope note:** other action types (`/SubmitForm`, `/URI`, `/RichMedia`) are not flagged.
  They do not execute code on open, and the pipeline never follows them.
- **Milestone:** M1

## D-017 Prompt-injection scanner: flag, never block; normalise first

- **Flag, don't block:** a flagged document is still analysed as data, with an
  `INJECTION_SUSPECTED` warning per page. Blocking would let an attacker suppress a legitimate
  report just by including a trigger phrase, and the analyst should see what the document
  tried to do.
- **Normalisation before matching:** NFKC (full-width letters become ASCII), removal of
  zero-width and bidi characters, whitespace collapsed, lower-cased. Each evasion has a test.
- **Specific patterns:** phrases like "act as" or "override" are deliberately not patterns,
  because they are common in incident reports. Negative tests pin down ordinary prose ("the
  driver ignored the red light").
- **No echo:** the warning names the matched *categories* (e.g. `ignore_instructions`), never
  the matched text, because the warning is shown in the UI and the text is attacker-controlled.
- **Hidden text is scanned:** white or tiny text that a human cannot see is still in the text
  layer, so it is still scanned (`prompt_injection.pdf` page 2).
- **Milestone:** M1 (scanner on the text layer). M2 adds scanning of vision transcriptions,
  since injection can also arrive inside an image.

## D-018 Single source for test fixtures and demo files

- **Why:** `backend/tests/pdf_factory.py` builds every fixture in memory. The pytest tests and
  `scripts/generate_adversarial_pdfs.py` both use it, so the committed demo files are exactly
  what the tests exercise. The script also re-validates each file and fails on any mismatch.
  Builders use fixed metadata, `reproducible=True` and `no_new_id=True`, so output is
  byte-identical across runs (apart from the encrypted file's random salt).
- **Milestone:** M1

## D-019 One error envelope for every failure path

- **Why:** the client parses one shape. `ApiError` (application errors), Starlette HTTP errors
  (404, 405), request validation (422) and unexpected exceptions (500) all render
  `{"error": {code, message, details}}`.
- **Leak prevention:** 422 details include the location and reason but not the submitted
  value (`input`), so document text cannot be echoed back. 500 responses say only "An
  unexpected error occurred", and the traceback goes to the server log.
- **Milestone:** M1

## D-020 PII masking scope

- **Patterns:** NRIC/FIN `[STFGM]\d{7}[A-Z]` (case-insensitive), Singapore phone numbers (8
  digits starting 3/6/8/9, optional `+65`/`65`, optional space or hyphen), and `+`-prefixed
  international numbers. Lookarounds stop digits inside longer numbers from being partly masked.
- **Trade-off accepted:** an 8-digit reference number starting with 3, 6, 8 or 9 will be masked.
  Masking too much is safer than leaking a number.
- **Where applied:** `mask_pii_in()` runs recursively over structured model output (from M2/M3).
  Dict keys are untouched because they are schema field names.
- **Milestone:** M1 (module and tests), wired into outputs in M2/M3

---

## Pending decisions (to record when made)

- Final Ollama model tag (verify `qwen3-vl:4b-instruct` exists in M2).
- Triage rubric (M7), as per spec section 8.
