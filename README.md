# HTX Document Analyst

[![CI](https://github.com/MuffinC/HTXTHA/actions/workflows/ci.yml/badge.svg)](https://github.com/MuffinC/HTXTHA/actions/workflows/ci.yml)

A fully local web application that helps Home Team analysts work through several incident tickets and reports at once: key details for each document, checks of each reporter's account against their own photos, a consolidated report across documents, and a suggested severity (triage) that the analyst confirms or overrides.

<!-- CHECK: give each video a one-line caption saying what it shows -->
*Walkthrough: …*

https://github.com/user-attachments/assets/792b719c-f43f-4b96-a751-06e53b10fb31

*…*

https://github.com/user-attachments/assets/ef2c2da5-0e83-48b9-9dcc-054648429ecf

*…*

<img width="1000" height="804" alt="key-details" src="https://github.com/user-attachments/assets/47a7fe46-4c7d-4191-ab55-92017ea9610d" />

## Contents

1. [Solution overview](#1-solution-overview)
2. [Architecture](#2-architecture)
3. [Setup instructions](#3-setup-instructions)
4. [Screenshots](#4-screenshots)
5. [Sample documents](#5-sample-documents)
6. [Output structure](#6-output-structure)
7. [Error handling and security](#7-error-handling-and-security)
8. [Optional AI feature: Triage](#8-optional-ai-feature-triage)
9. [Assumptions](#9-assumptions)
10. [Known limitations](#10-known-limitations)
11. [Use of AI-assisted tools](#11-use-of-ai-assisted-tools)
12. [Future work](#12-future-work)

---

## 1. Solution overview

### The problem
An analyst often receives several tickets and reports about the same incident, from different people, with photos attached. Reading them one by one is slow, and the useful signals are spread across documents: where the accounts disagree, whether a photo actually supports what the reporter wrote, and which incident needs attention first. The content is sensitive, so sending it to a cloud AI service is not an option. The question I set out to answer: can a fully local AI pipeline speed this up while keeping every claim verifiable and leaving the decisions to the analyst?

### What the app does
The analyst uploads one or more PDFs and picks an analysis profile. Each file is validated, then extracted page by page. Pages with photos, charts or scans are rendered and described by a local vision-language model. Each document gets its key details (summary, topics, entities, notable points), every one citing its page, and the documents are then compared in a consolidated report. With the Incident profile, the app also checks each reporter's account against their own photos, groups reports that describe the same incident, lists the contradictions between them, and suggests a priority for each report.

### Analysis profiles
| Profile | Best for | Adds to the core output |
|---|---|---|
| General | Any document (news, reports, statistics releases) | Core output only: summary, topics, entities, notable points and visual descriptions, all with page citations. The consolidated report is written by the model. |
| Incident | Incident tickets and reports with photos | The reporter's facts with exact quotes, structured photo scene fields, narrative-vs-photo consistency checks, same-incident grouping, rule-based contradictions and timeline, and triage |

A Statistical profile appears in the UI as "coming later". It was planned but not built (see [Future work](#12-future-work)).

### Key design principles
- **Fully local inference:** every model runs on the analyst's own machine through Ollama, so no document content ever leaves it. That rules out cloud APIs, including free tiers that may use submitted data to improve their products.
- **Analyst in the loop:** the AI suggests and the analyst decides. Every triage result needs human review, and the analyst can confirm it or override it with a reason.
- **Verifiable output (page citations):** every claim cites the page it came from, so the analyst can check it against the original. Citations pointing to pages that don't exist are removed, and the analyst is told.
- **Observation vs inference:** for photos, the model must keep what is directly visible ("front bumper crushed") separate from conclusions that go beyond it ("the car appears to have struck the tree"), and give the visible basis for each conclusion. It never identifies people or assigns fault. The analyst can then tell which statements are seen and which are reasoned.
- **Document content treated as untrusted:** text inside a document (or inside an image) is data to analyse, never instructions. A PDF that says "ignore previous instructions" is flagged as a possible prompt injection, and the system is built so that such text can't change the results unnoticed.
- **The model extracts, code compares:** in the Incident profile, the model only fills in fixed fields (traffic light colour, number of vehicles, weather…), each with an exact quote. Code then does every comparison with written rules, so results are repeatable and every finding can be explained.

---

## 2. Architecture

```mermaid
flowchart LR
    U[Analyst browser] --> F[Frontend<br/>React + nginx]
    F -->|/api| B[Backend<br/>FastAPI]
    B --> V[Validation &<br/>security checks]
    V --> Q[(Job queue)]
    Q --> W[Pipeline worker]
    W --> E[PDF extraction<br/>PyMuPDF]
    W --> O[Ollama<br/>vision-language model]
    W --> R[Rule engine<br/>incident comparisons,<br/>triage floor]
    W --> DB[(SQLite<br/>jobs, results, feedback)]
    B --> DB
```

### Processing pipeline
1. **Validation:** checks that each file really is a PDF (by its content, not its extension), and that it is within the size and page limits, not encrypted, not corrupt, and free of active content such as JavaScript. Rejected files get a clear reason; the other files in the upload carry on.
2. **Extraction (per page):** pulls out text and tables with no AI, then decides which pages need the vision model, and why: an embedded photo, a vector-drawn chart, or a scanned page. The text is also scanned for prompt-injection attempts, which are flagged but still analysed as data.
3. **Visual analysis:** renders the flagged pages and has the local model describe them in a structured JSON format (observations, possible inferences, information gaps, chart values). If a page fails, it becomes a warning and the document carries on.
4. **Document analysis:** combines the text from stage 2 with the descriptions from stage 3 and produces the key details, each with a page citation. With the Incident profile, a second model call extracts the reporter's facts with quotes, code checks them against the photos, and triage suggests a priority.
5. **Consolidated report:** compares all the documents. With the General profile the model writes the whole report. With the Incident profile, code groups reports of the same incident and computes the contradictions, agreements and timeline; the model only writes the summary text.
6. **Triage (optional feature):** code sets a minimum priority from the extracted facts (for example, a weapon gives P1). The model may raise it, but only with a quote that code finds on the cited page, and it can never lower it. The analyst confirms or overrides the result with a reason.

### Key design decisions
| Decision | Alternatives considered | Why |
|---|---|---|
| Local model via Ollama | Cloud APIs (Gemini free tier, OpenAI) | The reports and tickets are confidential, so no document content may leave the machine. Ollama runs the model locally and in Docker. |
| Render the whole page for visual analysis | Extract embedded images only | Many charts are drawn as vector graphics, not embedded images, so image extraction misses them completely; scanned pages have no separate images either. Rendering the page catches all of these with one model call per page. The trade-off: small images get less resolution, and the model can read text printed on the page (see Known limitations). |
| Single vision-language model for text and images | Separate OCR model + text model | One model handles both, which keeps the stack small. On an 8 GB GPU it fits comfortably (about 4.4 GB of VRAM) and takes about 3–5 s per page once loaded. |
| Async job queue with polling | Synchronous request | Analysis takes seconds to minutes (about 2 minutes for five tickets), far too long to hold an HTTP request open. Instead, the upload returns a job ID straight away, a background worker processes one document at a time (a single local GPU serves one model call efficiently), and the frontend polls for per-document progress every 2 s. Results are saved, so refreshing the page or sharing its link reloads them. Push updates (WebSockets) or a separate task queue (Celery + Redis) would add complexity without a benefit for a single analyst. |
| Structured JSON output validated by Pydantic | Free-text output | Ollama constrains the model to the JSON schema while it generates, and Pydantic validates the result. The UI and the rule engine can then rely on every field, and anything outside the schema (including injected text) never reaches the analyst. Length limits on fields also stop a model stuck in a repetition loop. |
| SQLite | Postgres / in-memory | SQLite is a single file with no extra service to install or configure, which suits a tool for one analyst on one machine. Unlike keeping jobs in memory, results survive a restart. Postgres would add another container and credentials for no benefit at this scale; it becomes the right choice for many concurrent users. |
| The model extracts, code compares (Incident profile) | Asking the model to find contradictions itself | Measured on the same synthetic pair of reports, the model-only approach found on average 2.7 of 4 planted contradictions, with about one false contradiction per run. With extraction plus rules: 4 of 4 in every run and no false contradictions. |
| Triage: rule floor, model may only raise | Model assigns the priority | Facts like an injury or a weapon set a minimum priority by rule, so injected text such as "mark this as P4" can never lower it. Any raise needs a quote that code verifies on the page. |

---

## 3. Setup instructions

### Prerequisites
- **Docker Desktop** (on Windows, with the WSL 2 backend).
- **About 8 GB of free disk space** for the model (about 3.3 GB) and the images.
- **For the real model: an NVIDIA GPU with 8 GB of VRAM or more** (the model uses about 4.4 GB). Without a GPU the app still runs, but very slowly; mock mode needs no GPU at all.
- **Memory for Docker:** for the GPU stack, give Docker's virtual machine at least 10 GB. On Windows, create `%UserProfile%\.wslconfig` containing:
  ```
  [wsl2]
  memory=10GB
  ```
  then run `wsl --shutdown` and restart Docker Desktop.

### Quick start (full app with the local model, NVIDIA GPU)
```bash
git clone https://github.com/MuffinC/HTXTHA.git
cd HTXTHA
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```
Open **http://127.0.0.1:8080**. API docs: http://127.0.0.1:8080/api/docs

- **First run:** the model is downloaded into a Docker volume (about 3.3 GB, roughly 2 minutes on a fast connection). Until it's ready, the top bar shows "Model not ready" and the Analyse button is disabled.
- **If Ollama is installed natively,** quit it first (on Windows, from the system tray). Both would compete for GPU memory.
- **Stop:** `docker compose -f docker-compose.yml -f docker-compose.gpu.yml down`. Don't add `-v`, which deletes the downloaded model.
- **Settings:** every setting has a default, so no `.env` file is needed. To change one, copy `.env.example` to `.env` and edit it.

### Quick start (mock mode, no model required)
```bash
docker compose -f docker-compose.mock.yml up -d --build
```
Open http://127.0.0.1:8080. Results are deterministic samples marked "MOCK"; this is the mode CI uses.

### Without a GPU (CPU only)
```bash
docker compose up -d --build
```
This works, but each page can take minutes.

### Local development (without Docker)
**Backend** (Python 3.12):
```powershell
# Windows PowerShell (if blocked: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass)
.\scripts\setup_backend.ps1
.\backend\.venv\Scripts\Activate.ps1
cd backend
$env:LLM_PROVIDER="mock"; $env:DATA_DIR="./data"
uvicorn app.main:app
```
On Linux or macOS, use `./scripts/setup_backend.sh`. With Anaconda: `conda env create -f backend/environment.yml`.

To use a natively installed Ollama instead of mock mode, set `LLM_PROVIDER=ollama` and `OLLAMA_BASE_URL=http://127.0.0.1:11434`. On an 8 GB GPU, also set `OLLAMA_FLASH_ATTENTION=1` and `OLLAMA_KV_CACHE_TYPE=q8_0` as environment variables for Ollama itself, then restart it. Use `127.0.0.1` rather than `localhost`, which can resolve to IPv6.

**Frontend** (Node 24):
```bash
cd frontend
npm ci
npm run dev
```
Open http://127.0.0.1:5173. The dev server forwards `/api` to the backend on port 8000.

### Running tests
```bash
# Backend: unit tests, mock provider only
cd backend
pytest
# Live tests against the real model (needs Ollama running)
pytest -m ollama

# Frontend
cd frontend
npm run lint
npm run typecheck
npm test
npm run build

# Smoke test against a running stack (Git Bash or Linux)
bash scripts/smoke_test.sh http://127.0.0.1:8080 120
```
On Windows, run the frontend tests from PowerShell. Vitest fails when the working directory starts with a lowercase drive letter (`c:\`), which some shells pass on.

### Configuration
The main settings (full list in `.env.example`):

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `ollama` (local model) or `mock` (no model) |
| `OLLAMA_MODEL` | `qwen3-vl:4b-instruct` | Vision-language model tag |
| `OLLAMA_NUM_CTX` | `16384` | Context window |
| `LLM_TIMEOUT_SECONDS` | `300` | Time limit per model call |
| `MAX_FILES` / `MAX_FILE_MB` / `MAX_PAGES` | `10` / `25` / `60` | Upload limits |
| `MAX_VISUAL_PAGES_PER_DOC` | `20` | Pages per document sent to the vision model |
| `RENDER_DPI` | `150` | Page rendering resolution |
| `ACTIVE_CONTENT_POLICY` | `reject` | PDFs with JavaScript or launch actions |
| `EMBEDDED_FILE_POLICY` | `warn` | PDFs with attached files (never opened) |
| `MASK_PII` | `true` | Mask NRIC/FIN and phone numbers in output |
| `RETAIN_UPLOADS` | `false` | Keep uploaded PDFs after processing |
| `FRONTEND_PORT` | `8080` | Port on 127.0.0.1 |

---

## 4. Screenshots

All screenshots and clips use the real model, except where marked "mock mode".

### Upload with profile selection

https://github.com/user-attachments/assets/74d32155-c480-4225-b318-0267ad1d9312

### Processing states

https://github.com/user-attachments/assets/07d302e3-db88-436e-924d-82de35744de5

### Per-document key details and visual evidence (Incident profile)
<img width="1574" height="1003" alt="image" src="https://github.com/user-attachments/assets/7a4f2411-9eb0-4da1-8a3e-ba1c51f9ab62" />
<img width="1159" height="779" alt="image" src="https://github.com/user-attachments/assets/33f06e15-4125-4323-8983-876c34110285" />
<img width="1135" height="952" alt="image" src="https://github.com/user-attachments/assets/42a027a3-b7aa-4c5e-8e25-b40b68bd9dcb" />
<img width="1133" height="599" alt="image" src="https://github.com/user-attachments/assets/2198f650-dd40-451f-acde-d5ff318cd857" />
<img width="760" alt="Document view: key details and visual evidence" src="https://github.com/user-attachments/assets/124400f5-7997-436e-ba5f-7cf83d18944b" />

### Consolidated report (Incident profile)
<img width="1730" height="1274" alt="image" src="https://github.com/user-attachments/assets/286b02c0-21c2-418a-8962-bb86b7b90c16" />
<img width="1153" height="1040" alt="image" src="https://github.com/user-attachments/assets/7c9cbd95-0617-439f-9931-103d271fa4e3" />

### Why the Incident profile compares by rule
The same five tickets under the General profile, where the model writes the consolidated report itself. It wrongly treats D2 as a different incident and dates it 15 March ("last night" in a report submitted on 15 March means the 14th). Under the Incident profile, the rules group and date them correctly.

<img width="1000" alt="General profile consolidated report with model errors" src="https://github.com/user-attachments/assets/5fffb1e9-6a77-43cb-92df-317bfc712842" />

### Triage and analyst override

<img width="1000" alt="Triage confirm and override" src="https://github.com/user-attachments/assets/23788e7b-8e08-4810-8223-3b9f17fd7226" />

### Error handling (rejected and adversarial files)

<img width="1000" alt="Rejected files and prompt-injection warning" src="https://github.com/user-attachments/assets/ee120bbe-67be-414a-b374-12099362d0de" />

![Prompt-injection warning](docs/images/prompt-injection.jpg)

### Running locally with Docker Compose

![All containers healthy](docs/images/compose-run.jpg)

### CI pipeline

<img width="1000" alt="CI pipeline: backend, frontend and Docker jobs passing" src="https://github.com/user-attachments/assets/059ba4ad-6055-4e81-b05b-00fb3a91f862" />

---

## 5. Sample documents

All samples are in [`sample_pdfs/`](sample_pdfs/). Sources, licences and the expected results for each file are in [`sample_pdfs/README.md`](sample_pdfs/README.md).

| File | Type | Purpose |
|---|---|---|
| `tickets/t1_witness.pdf` | Synthetic ticket | Witness account of a junction collision |
| `tickets/t2_taxi_driver.pdf` | Synthetic ticket | Same incident, taxi driver; date given as "last night" |
| `tickets/t3_passenger.pdf` | Synthetic ticket | Same incident, passenger; doesn't mention the traffic light (tests that absence is never a contradiction) |
| `tickets/t4_unrelated_tree.pdf` | Synthetic ticket | Unrelated incident whose narrative (night, heavy rain) contradicts its own photo (daylight, dry road) |
| `tickets/t5_weapon_variant.pdf` | Synthetic ticket | Separate incident involving a knife (tests the P1 triage rule) |
| `general/` <!-- CHECK: filename --> | Public document | NHTSA research note, crash statistics with trend charts (US public domain) |
| `general/` <!-- CHECK: filename --> | Public document | NHTSA research note, previous year (US public domain) |
| `general/` <!-- CHECK: filename --> | Public document | NTSB Highway Accident Brief with crash photos and diagrams (US public domain) |
| `adversarial/prompt_injection.pdf` | Adversarial | Visible and hidden (white-on-white) instructions to the AI: accepted, flagged |
| `adversarial/vector_chart.pdf` | Test file | A chart drawn with vectors and no embedded images |
| `adversarial/fake_pdf.pdf` | Adversarial | A text file renamed to `.pdf`: rejected |
| `adversarial/encrypted.pdf` | Adversarial | Password-protected (password `htx-demo`): rejected |
| `adversarial/javascript.pdf` | Adversarial | Contains JavaScript: rejected |
| `adversarial/too_many_pages.pdf` | Adversarial | 61 pages: rejected |
| `adversarial/empty.pdf` | Adversarial | No content: rejected |
| `adversarial/corrupt.pdf` | Adversarial | Damaged file: rejected |

**Referenced, not included:** two Singapore Police Force releases, the [Annual Road Traffic Situation 2025](https://www.police.gov.sg/-/media/SPF/Media-Room/Statistics/Annual-Road-Traffic-Situation-2025/Annual-Road-Traffic-Situation-2025.pdf) and the [Mid-Year Road Traffic Situation 2026](https://www.police.gov.sg/-/media/SPF/Media-Room/Statistics/Mid-Year-Road-Traffic-Situation-2026/Mid-Year-Road-Traffic-Situation-2026.pdf). They're linked rather than committed because their reuse terms are unconfirmed.

**Why the tickets are synthetic:** real incident reports aren't publicly available. The tickets are e-report forms from a fictional portal ("CityWatch e-Report"), with real Singapore road names but invented events, people and reference numbers, placeholder contact numbers, and a "SYNTHETIC SAMPLE" footer on every page. T1–T3 describe the same collision from three reporters, with deliberate contradictions (time, traffic light, number of vehicles, weather, injuries, a vehicle leaving the scene), so the results can be measured against known answers. They're generated by `scripts/generate_sample_tickets.py`.

---

## 6. Output structure

Every analysed document has the same core fields. The Incident profile adds `incident` and `triage`, and each job has one consolidated report. A trimmed example (T4, Incident profile):

```json
{
  "document_id": "…",
  "filename": "t4_unrelated_tree.pdf",
  "page_count": 2,
  "profile": "incident",
  "summary": "A driver reported their car skidded and hit a roadside tree…",
  "main_topics": ["Road traffic accident", "Weather conditions"],
  "key_entities": [{ "name": "Upper Thomson Road near Lower Peirce Reservoir", "type": "location", "pages": [1] }],
  "notable_points": [{ "point": "The report was submitted on 18 March 2025 at 09:30.", "page": 1 }],
  "visual_elements": [{
    "page": 2,
    "type": "photo",
    "observations": ["The front of the vehicle is embedded into a tree trunk."],
    "possible_inferences": [],
    "information_gaps": ["The cause of the collision is not known."],
    "scene": { "lighting": "daylight", "road_surface": "dry", "damage_locations": ["front"] },
    "ai_generated": true
  }],
  "incident": {
    "facts": {
      "weather": { "value": "rain", "as_written": "It was raining heavily", "page": 1 },
      "lighting": { "value": "night_dark", "as_written": "it was very dark", "page": 1 }
    },
    "consistency_checks": [{
      "check": "Weather: narrative vs photo",
      "result": "inconsistent",
      "details": "Reporter: rain (\"It was raining heavily\"). Photo: photo shows a dry road (p.2).",
      "pages": [1, 2]
    }]
  },
  "triage": {
    "suggested_priority": "P3",
    "rule_priority": "P3",
    "triggering_factors": [{ "factor": "No injuries reported", "source": "rule" }],
    "requires_human_review": true,
    "analyst_override": null
  },
  "warnings": []
}
```

The consolidated report has an overall summary (with a rule-based opening line such as "3 reports describe 1 incident; 2 reports describe separate incidents. 1 report includes photos (D4)."), same-incident groups with their reasons, contradictions and agreements (each position quoted with its document and page), a timeline, common themes and information gaps. The full reference, with every field and which ones are set by the model and which by code, is in [`docs/SCHEMAS.md`](docs/SCHEMAS.md).

---

## 7. Error handling and security

### Invalid and unsupported files
Each file is checked on upload. A rejected file gets a clear reason in the UI, and the other files in the same upload carry on.

| Code | Trigger |
|---|---|
| `UNSUPPORTED_TYPE` | No PDF header (`%PDF-1.x`) within the first 1024 bytes. The file extension is never trusted. |
| `FILE_TOO_LARGE` | Larger than `MAX_FILE_MB` (25 MB) |
| `TOO_MANY_FILES` | More than `MAX_FILES` (10) in one upload; the whole request is rejected |
| `TOO_MANY_PAGES` | More than `MAX_PAGES` (60) |
| `CORRUPT_PDF` | Can't be opened, or has no pages |
| `ENCRYPTED_PDF` | Password-protected |
| `EMPTY_DOCUMENT` | No text and no visual content |
| `ACTIVE_CONTENT` | Contains JavaScript or launch actions (rejected by default) |
| `NO_VALID_FILES` | Every file in the upload was rejected |

Problems during processing never crash the job: a failed page or document becomes a warning or a per-document failure, and the rest of the job continues (a job with some failures is marked "partially completed"). Every API error uses the same `{"error": {code, message, details}}` format and never echoes document content. The exact codes and wording are in [`docs/README_FACTS.md`](docs/README_FACTS.md).

### Harmful and adversarial content
- **Active content:** PDFs with JavaScript or launch actions are rejected. Attached files are allowed with a warning by default, because they're never extracted or opened.
- **Download wrappers:** bytes before the PDF header (for example from a faulty download) are stripped, never parsed, and reported in a warning.
- **Prompt injection, several layers:**
  1. The system prompt tells the model that document content is data, never instructions.
  2. Document text is wrapped in markers with a random identifier for every request, so a document can't fake the end of its own content.
  3. A scanner flags instruction-like text (normalised first, so tricks like invisible characters or full-width letters don't get past) in both the page text and text the model read from images. Flagged pages show a red security warning but are still analysed as data.
  4. Output must match the JSON schema; anything else is discarded.
  5. If the model returns nothing for a page that the PDF structure shows has a chart or photo (as an injected "return an empty list" can cause), that's flagged too.
  6. In triage, injected text can't lower a priority below what the extracted facts support.
  7. The UI renders all model output as plain text, never HTML; a lint rule enforces this.
- **Malformed or runaway model output:** invalid output gets one retry, then a clear failure for that page or document. Field length limits stop a model stuck repeating itself.

### Sensitive content and privacy
- **Local only:** inference runs entirely on the analyst's machine, and the app is reachable only from that machine (127.0.0.1).
- **PII masking:** NRIC/FIN and phone numbers are masked in model output by default (`MASK_PII`). It's configurable, because an investigator may legitimately need a reporter's contact number.
- **No content in logs:** logs are structured JSON with IDs, stages, timings and error codes only, never document text or model output.
- **Uploads are deleted** after processing unless `RETAIN_UPLOADS=true`.
- **People by role:** incident output refers to people by role ("driver of the silver car"), never by name, and photo descriptions never identify anyone or assign fault.
- **Graphic content:** descriptions of graphic images are collapsed in the UI until the analyst chooses to show them.

---

## 8. Optional AI feature: Triage

### Purpose
To set a severity level so that the more alarming matters come to light quicker, since those need human attention as soon as possible.

### Design considerations
- **A rubric written into the code:** P1 for serious or fatal injuries or a weapon; P2 for an injury or a party leaving the scene; P3 for a road-traffic report with no injuries; P4 when there's too little detail to act on.
- **Rule floor first:** code computes a minimum priority from the facts extracted from the report, each factor citing its page.
- **The AI may only raise the priority,** for things the fixed fields don't cover, and only with a short quote that code finds on the cited page. Otherwise the raise is ignored. Injected text can therefore never lower a priority; the reverse risk (an injected escalation) is the deliberate safety-first trade-off, and every result still needs analyst review.
- **Weapons are a fact, not a judgement:** a quote-checked `weapon` fact gives P1 by rule. That covers a case the 4B model missed when it was asked to notice weapons itself.
- **Groups:** a same-incident group takes its reports' highest priority. It's lifted further only by contradictions on safety-relevant facts (traffic light, injuries, vehicle count, a party leaving, a weapon), not by small differences in reported times.
- **Analyst in the loop:** every result is marked "needs analyst review". The analyst confirms it or overrides it with a required reason, and the UI shows "Suggested P3 → Analyst P2" with the reason and time. Thumbs up/down feedback and a triage agreement rate (how often analysts keep the suggestion) are stored for evaluating future prompt changes, never for training.

This requires more knowledge of how police and analysts define severity, as I based the rubric on what I know as a baseline. A lot can be improved here after receiving user feedback.

---

## 9. Assumptions

Full list with IDs: [`docs/ASSUMPTIONS.md`](docs/ASSUMPTIONS.md). The main ones:

**Users and scope**
- One analyst on one machine. There is no login or multi-user isolation (A-001).
- Analysts are authorised to see the documents' personal details, so PII masking is on by default but can be turned off.

**Data**
- All sample documents are fictional (the synthetic tickets) or public (A-002).
- Uploads are text-based or scanned PDFs, in English.

**Hardware and model**
- The full experience assumes an NVIDIA GPU with 8 GB of VRAM. The model is a 4-billion-parameter vision-language model (`qwen3-vl:4b-instruct`), chosen to fit that card.
- Docker's virtual machine has at least 10 GB of memory for the GPU stack (A-306).
- The app is opened from the same machine (127.0.0.1), in a current browser.

**Incident rules**
- Reporters' times are estimates: reports within 60 minutes of each other can be the same incident, and times more than 10 minutes apart count as a contradiction (A-123).
- If a report gives a time but no date, the incident is assumed to be the latest occurrence of that time before the report was submitted. The UI marks this "(assumed)" (A-121).
- Relative dates are resolved only for a fixed list of phrases such as "last night" and "yesterday" (A-124).
- Expected lighting uses fixed Singapore daylight hours: daylight 07:15–19:00, dusk or dawn 30 minutes either side, otherwise night (A-122).
- Numeric dates are day-first, as written in Singapore.

---

## 10. Known limitations

The full list, with IDs, is in [`docs/ASSUMPTIONS.md`](docs/ASSUMPTIONS.md). The most important:

- **Speed:** without a GPU, analysis is very slow. On an RTX 3070 it takes about 3–5 s per page once the model is loaded, and about 2 minutes for the five sample tickets.
- **Small model accuracy:** a 4B model can still be wrong. For example, its own summary text can disagree with the rule-based findings shown directly above it, and its photo descriptions are accurate but sparse.
- **The AI's triage raise rarely fires** on the 4B model. The important cases (injuries, weapons) are therefore handled by rule.
- **Whole-page rendering:** small images get less resolution, and the model can read text printed on the page, which can leak into "observations" about a photo. Cropping to the photo's area would fix both.
- **Prompt-injection detection is heuristic:** a phrase list can't catch every wording. The other layers limit the damage, but a small model can still be steered by text on a page; the system flags this rather than preventing it.
- **Location matching has no gazetteer:** "AMK Hub" and "Ang Mo Kio Ave 3" aren't recognised as the same place.
- **Single worker, single user:** one job at a time, with no authentication.
- **Docker Desktop with 8 GB of memory** stopped responding during long test runs; 10 GB or more is recommended for the GPU stack.
- **The API docs page** (`/api/docs`) loads its scripts from a public CDN, so it doesn't render offline. The app itself is unaffected.
- **PyMuPDF is AGPL-3.0 licensed,** which matters for an agency deployment; pypdfium2 plus pdfplumber is the permissively licensed alternative.
- **The synthetic sample tickets** may not reflect real-world reports.

---

## 11. Use of AI-assisted tools

<!-- CHECK: edit this into your own words -->
I planned the solution with Claude: the problem framing, the architecture, the output schemas and each milestone's scope. The implementation was done by Claude Code against a written specification (`CLAUDE.md`), one milestone at a time. After each milestone I reviewed the summary and the design decisions, ran the tests and the app myself, and reviewed the screenshots. My review led to changes such as removing confusing UI labels, simplifying the triage design, and time-boxing prompt tuning in favour of rules in code. Every design decision and assumption is recorded in `docs/DECISIONS.md` and `docs/ASSUMPTIONS.md`.

---

## 12. Future work

- Crop to embedded images instead of rendering the whole page, for sharper photos and no page-text leakage.
- A larger model on a bigger GPU, compared using the existing scorecard.
- Location matching with a gazetteer or postal-code lookup.
- The Statistical profile: key figures, trends and the reporting period.
- Page image previews beside the citations.
- Authentication, user accounts and an audit trail.
- An evaluation harness built on the analyst feedback that's already collected.
