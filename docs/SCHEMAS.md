# Output schema reference

Human-readable reference for the API and LLM output schemas.

**Source of truth:** the Pydantic models in `backend/app/schemas/`. The TypeScript types in
`frontend/src/` mirror them. Keep this file in sync whenever either changes. The design-level
definitions are in `CLAUDE.md` section 8.

## Implemented

### `GET /api/health` → `HealthResponse`

| Field | Type | Meaning |
|---|---|---|
| `status` | `"ok" \| "degraded"` | `ok` when the model is usable; `degraded` when Ollama is unreachable or the model is not pulled yet |
| `provider` | `"ollama" \| "mock"` | Active LLM provider (`LLM_PROVIDER`) |
| `model` | `string` | Configured Ollama model tag, or `"mock"` |
| `model_ready` | `boolean` | Ollama is reachable and lists the model (always `true` in mock mode) |

### Error envelope (every API error) — `app/schemas/errors.py`

```json
{"error": {"code": "TOO_MANY_FILES", "message": "11 files were uploaded; the limit is 10 per upload.",
           "details": {"max_files": 10, "received": 11}}}
```

| `code` | HTTP | Raised when |
|---|---|---|
| `UNSUPPORTED_TYPE` | per file | Content does not start with `%PDF-` (extension and MIME ignored) |
| `FILE_TOO_LARGE` | per file | Larger than `MAX_FILE_MB` (25) |
| `TOO_MANY_FILES` | 400 | More than `MAX_FILES` (10) in one upload |
| `TOO_MANY_PAGES` | per file | More than `MAX_PAGES` (60) |
| `CORRUPT_PDF` | per file | PyMuPDF cannot open it, or it has 0 pages |
| `ENCRYPTED_PDF` | per file | A password is required to open it |
| `EMPTY_DOCUMENT` | per file | No text, images or drawings on any page |
| `ACTIVE_CONTENT` | per file | JavaScript, launch action or embedded file, with `ACTIVE_CONTENT_POLICY=reject` |
| `NO_VALID_FILES` | 400 | Every file in an upload was rejected (used from M3) |
| `VALIDATION_ERROR` | 422 | Malformed request; `details.errors[]` has `loc`, `msg` and `type`, but never the submitted value |
| `NOT_FOUND` / `METHOD_NOT_ALLOWED` | 404 / 405 | Unknown route or method |
| `INTERNAL_ERROR` | 500 | Unexpected failure; no internals exposed |

"Per file" codes appear in the `rejected[]` list of `POST /api/jobs` (M3) as `RejectedFile`
(`app/schemas/validation.py`): `{filename, code, message}`. `filename` is sanitised for display.

### `Warning` — `app/schemas/common.py` (Python class `DocumentWarning`)

| Field | Type | Meaning |
|---|---|---|
| `code` | `WarningCode` | See below |
| `message` | `string` | Human-readable. Never contains attacker-controlled text |
| `page` | `int \| null` | 1-based page, when the warning is page-specific |

`WarningCode`: `INJECTION_SUSPECTED` (per page), `ACTIVE_CONTENT` (only with policy `warn`),
`VISUAL_PAGES_CAPPED` (lists the skipped pages), `TABLE_EXTRACTION_FAILED` (per page),
`VISUAL_ANALYSIS_FAILED` (per page, from M2).

### Internal pipeline records (not API output) — `app/schemas/extraction.py`

`PageContent`: `page` (1-based), `text`, `tables` (markdown strings), `needs_visual_analysis`,
`visual_reasons` (`embedded_image` | `vector_drawing` | `scanned`), `visual_area_ratio`
(0–1, used for ranking), `selected_for_visual_analysis`.
`ExtractedDocument`: `page_count`, `pages`, `warnings`.

## Planned (to be documented as implemented)

| Schema | Milestone |
|---|---|
| `Citation`, `Entity`, `NotablePoint`, `VisualElement` | M2 |
| `DocumentAnalysis` (core) | M3 |
| `ConsolidatedReport` | M3 |
| `IncidentExtension` | M6 |
| `Triage` | M7 |
| `StatisticalExtension` | M8 |
