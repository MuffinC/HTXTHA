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

### `GET /api/config` → `ConfigResponse` — `app/api/config.py`

Display-safe settings the frontend needs (DECISIONS D-045): `max_files`, `max_file_mb`,
`max_pages`, `max_visual_pages_per_doc`, `active_content_policy` (`reject` | `warn`), `mask_pii`
and `retain_uploads`.

**TypeScript mirror:** `frontend/src/api/types.ts` mirrors every schema on this page. It is
checked against real API output by the typed fixtures in `frontend/src/test/fixtures/` (D-046).

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
| `NO_VALID_FILES` | 400 | Every file in an upload was rejected; `details.rejected[]` lists each file |
| `UNSUPPORTED_PROFILE` | 400 | Profile exists but is not available yet (`details.available`) |
| `VALIDATION_ERROR` | 422 | Malformed request; `details.errors[]` has `loc`, `msg` and `type`, but never the submitted value |
| `NOT_FOUND` / `METHOD_NOT_ALLOWED` | 404 / 405 | Unknown route or method |
| `INTERNAL_ERROR` | 500 | Unexpected failure; no internals exposed |

The `413 FILE_TOO_LARGE` variant is returned when a request's total `Content-Length` exceeds
`MAX_FILES x MAX_FILE_MB + 1 MB`.

"Per file" codes appear in the `rejected[]` list of `POST /api/jobs` as `RejectedFile`
(`app/schemas/validation.py`): `{filename, code, message}`. `filename` is sanitised for display.

### `Warning` — `app/schemas/common.py` (Python class `DocumentWarning`)

| Field | Type | Meaning |
|---|---|---|
| `code` | `WarningCode` | See below |
| `message` | `string` | Human-readable. Never contains attacker-controlled text |
| `page` | `int \| null` | 1-based page, when the warning is page-specific |

`WarningCode`: `INJECTION_SUSPECTED` (per page), `ACTIVE_CONTENT` (only with policy `warn`),
`VISUAL_PAGES_CAPPED` (lists the skipped pages), `TABLE_EXTRACTION_FAILED` (per page),
`VISUAL_ANALYSIS_FAILED` (per page: render error, timeout, refusal, invalid output, model
unavailable, or no elements returned for a page that stage 1 knows has visual content),
`CITATIONS_REMOVED` (the model cited pages or documents that do not exist; they were removed),
`CONTENT_TRUNCATED` (text was cut to fit the model's context; per page when page-specific).

### Internal pipeline records (not API output) — `app/schemas/extraction.py`

`PageContent`: `page` (1-based), `text`, `tables` (markdown strings), `needs_visual_analysis`,
`visual_reasons` (`embedded_image` | `vector_drawing` | `scanned`), `visual_area_ratio`
(0–1, used for ranking), `margin_lines` (text in the top/bottom 8% band: header/footer
candidates), `selected_for_visual_analysis`.
`ExtractedDocument`: `page_count`, `pages`, `warnings`, `boilerplate_lines` (running
headers/footers removed from page text; DECISIONS D-043).

### `Citation` — `app/schemas/common.py`

`{document_id: string, page: int (1-based)}`. Used by the consolidated report and triage (M3, M7).

### `VisualElement` — `app/schemas/visual.py`

One visual element on a page, produced by stage 2. Every field is AI-generated.

| Field | Type | Meaning |
|---|---|---|
| `page` | `int` | 1-based page (set by the pipeline, not the model) |
| `type` | `"photo" \| "chart" \| "table" \| "diagram" \| "map" \| "scanned_text"` | Decorative items are dropped |
| `description` | `string` | Factual description |
| `observations` | `string[]` | Only what is directly visible (max 25) |
| `possible_inferences` | `{inference, basis}[]` | Conclusions beyond what is visible, each with its visible evidence |
| `information_gaps` | `string[]` | What cannot be determined from the image |
| `table_markdown` | `string \| null` | Only for `table` |
| `chart` | `ChartDetails \| null` | Only for `chart`: `chart_type`, `x_axis`, `y_axis`, `key_values[]` ("label: value"), `trend`. **Addition to the spec** (DECISIONS D-026) |
| `transcription` | `string \| null` | Only for `scanned_text`. **Addition to the spec** (D-026) |
| `sensitive_content` | `{graphic: bool, pii_visible: PiiCategory[]}` | `graphic` collapses the item in the UI. `pii_visible` lists categories only: `face`, `licence_plate`, `identity_document`, `name`, `phone_number`, `address`, `signature`, `other` |
| `ai_generated` | `true` | Always true |

Text fields are PII-masked when `MASK_PII=true` (default).

**Model-facing schema (internal):** the model fills `VisualPageModelOutput`
(`instructions_to_ai_present: bool`, `elements: VisualElementModelOutput[]`,
`declined_reason: string | null`). Its JSON schema is sent as Ollama's `format`. The pipeline
maps it onto `VisualElement` (D-026).

### `DocumentAnalysis` — `app/schemas/analysis.py`

Per-document result (core schema, every profile). Fields set by the pipeline are marked (P);
the rest come from the model and are validated, citation-checked and PII-masked.

| Field | Type | Meaning |
|---|---|---|
| `document_id` (P) | `string` | Generated UUID |
| `filename` (P) | `string` | Sanitised, display only |
| `page_count` (P) | `int` | |
| `profile` (P) | `"general" \| "incident" \| "statistical"` | |
| `document_type_guess` | `string` | e.g. "incident report" |
| `summary` | `string` | 3–5 sentences |
| `main_topics` | `string[]` | |
| `key_entities` | `Entity[]` | `{name, type, pages[]}`; `type` is `person_role`, `organisation`, `location`, `date_time`, `vehicle`, `object` or `other`. Only real pages; entities with none are dropped |
| `notable_points` | `NotablePoint[]` | `{point, page}`; only real pages |
| `visual_elements` (P) | `VisualElement[]` | From stage 2 |
| `warnings` (P) | `Warning[]` | Upload, extraction, visual and analysis warnings |

`incident` (M6) and `triage` (M7) are documented below; `statistical` arrives in M8.

### `ConsolidatedReport` — `app/schemas/consolidated.py`

| Field | Type |
|---|---|
| `overall_summary` | `string` |
| `common_themes` | `{theme, citations: Citation[]}[]` |
| `agreements` | `{point, citations: Citation[]}[]` |
| `contradictions` | `{topic, positions: {position, citation: Citation}[]}[]` (at least 2 positions) |
| `timeline` | `{time, event, citations: Citation[]}[]` |
| `related_document_groups` | `DocumentGroup[]`: `{document_ids: string[], reason, priority?, priority_reason?}` (at least 2 documents; priority fields in the incident profile) |
| `information_gaps` | `string[]` |
| `warnings` | `Warning[]`. **Addition to the spec** (DECISIONS D-034) |

The model writes citations against labels `D1`, `D2`… (`LabelCitation {document, page}`), and
the pipeline maps them to document IDs (D-035). Items whose citations are all invalid are dropped.

### Jobs API — `app/schemas/jobs.py`

`POST /api/jobs` (multipart: `files` repeated, `profile` default `general`) returns
**202** `JobCreatedResponse`:

```json
{"job_id": "…",
 "accepted": [{"document_id": "…", "filename": "report.pdf", "page_count": 2, "warnings": []}],
 "rejected": [{"filename": "fake.pdf", "code": "UNSUPPORTED_TYPE", "message": "…"}]}
```

`GET /api/jobs/{job_id}` returns `JobResponse`:

| Field | Type | Meaning |
|---|---|---|
| `job_id`, `profile` | | |
| `status` | `queued \| processing \| completed \| partial \| failed` | See DECISIONS D-037 |
| `created_at`, `updated_at` | ISO datetime | `updated_at` changes on every document transition |
| `error` | `ErrorInfo \| null` | Job-level reason, e.g. `INTERRUPTED`, `NO_DOCUMENT_ANALYSED` |
| `documents` | `DocumentResult[]` | In upload order, including rejected files |
| `consolidated` | `ConsolidatedReport \| null` | |
| `consolidated_error` | `ErrorInfo \| null` | `SINGLE_DOCUMENT`, or the LLM error code if stage 4 failed |

`DocumentResult`: `document_id`, `filename`, `status` (`queued`, `validating`, `extracting`,
`analysing_visuals`, `analysing`, `completed`, `rejected`, `failed`), `page_count`, `error`,
`analysis` (`DocumentAnalysis` once completed).

`ErrorInfo`: `{code, message}`. The message is always written by the backend, never the model.
Document-level codes: the upload codes above (for `rejected`), `LLM_OUTPUT_INVALID` (still invalid
after one retry), `LLM_TIMEOUT`, `LLM_UNAVAILABLE`, `LLM_REFUSED`, `INTERNAL_ERROR` and
`INTERRUPTED`.

`GET /api/profiles` returns `ProfileInfo[]`: `{id, name, description, available}`.

### Incident profile — `app/schemas/incident.py` (DECISIONS D-057, D-058)

`DocumentAnalysis.incident: IncidentExtension | null` (set for the incident profile):

| Field | Type | Set by |
|---|---|---|
| `ticket` | `{reference_no, submitted_at, category, category_confidence}` | model (as written) |
| `occurred_at_stated`, `location_stated` | `string \| null` | model (as written) |
| `narrative_summary`, `parties` (`{role, description}[]`, roles only) | | model |
| `claims` | `{claim, page, corroboration: supported \| contradicted \| not_verifiable, note}[]` | code |
| `consistency_checks` | `{check, result: consistent \| inconsistent \| unclear, details, pages}[]` | code |
| `missing_information` | `string[]` | code plus model |
| `facts` (**addition**) | `IncidentFacts`: `traffic_light`, `vehicle_count`, `weather`, `road_surface`, `lighting`, `injuries`, `party_left_scene` as `{value, as_written, page}` (value from a closed list, or `not_mentioned`), plus `vehicle_types[]`, `damage_locations[]` | model, then quote-grounded by code |
| `derived` (**addition**) | `{incident_date, incident_time, expected_lighting}`, each `{value, source} \| null` | code |

`VisualElement.scene: SceneObservation | null` (**addition**; incident photos only):
`lighting`, `weather`, `road_surface`, `vehicles_visible`, `vehicle_types[]`,
`damage_locations[]`, `traffic_signal` (closed lists, each with `unclear`), and
`timestamp_visible` (as shown). The model must answer every field.

`ConsolidatedReport` (**additions**): `possibly_related_groups` (`DocumentGroup[]`) and
`rule_based` (`true` when contradictions, agreements, timeline and groups were computed by rule).
For the incident profile the model only writes `overall_summary`, `common_themes` and
`information_gaps` (`IncidentNarrativeOutput`).

Warning code `INCIDENT_EXTRACTION_FAILED`: the core analysis is kept, but the incident sections
are missing.

### Triage (incident profile) — `app/schemas/triage.py` (DECISIONS D-062 to D-066)

`DocumentAnalysis.triage: Triage | null` (incident profile only):

| Field | Type | Meaning |
|---|---|---|
| `suggested_priority` | `P1 \| P2 \| P3 \| P4` | The more severe of `rule_priority` and an accepted model raise |
| `rationale` | `string` | Written by code: the floor, and the raise or why it was ignored |
| `triggering_factors` | `{factor, citation: Citation, source: rule \| model}[]` | Every factor cites its page. **`source` is an addition** |
| `confidence` | `low \| medium \| high` | |
| `requires_human_review` | `true` | Always |
| `analyst_override` | `AnalystOverride \| null` | The latest analyst decision (attached by the API) |
| `rule_priority` (**addition**) | `Priority` | Floor computed by code from the grounded facts |
| `model_priority` (**addition**) | `Priority \| null` | Set only when a grounded raise was accepted |

`AnalystOverride`: `{action: confirm | override, priority, reason, at}` (`action` is an
addition to the spec).

Model output (`TriageModelOutput`, sent as Ollama `format`): `{proposed_priority, reason
(≤300), evidence: {quote (≤200), page}[] (≤4), confidence}`.

`DocumentGroup` (**additions**, incident profile): `priority: Priority | null` and
`priority_reason: string | null` (D-064).

**Endpoints**

- `PUT /api/jobs/{job_id}/documents/{document_id}/triage`, body
  `{action: "confirm" | "override", priority?, reason? (≤500)}` → `AnalystOverride`.
  422 `VALIDATION_ERROR` for an override without a priority or a reason of 5+ characters;
  404 `NOT_FOUND` for an unknown job or document, or a document without triage.
- `POST /api/jobs/{job_id}/feedback`, body `{target: document | consolidated | section,
  target_id (1–120 chars), rating: up | down, comment? (≤1000)}` → **201** `{id}`.
- `GET /api/feedback/stats` → `{ratings: {key: {up, down}}, total_up, total_down,
  triage_reviewed, triage_kept, triage_agreement_rate: float | null}`. Keys are
  `section:<target_id>` for sections, otherwise the target name.

## Planned (to be documented as implemented)

| Schema | Milestone |
|---|---|
| `StatisticalExtension` | M8 |
