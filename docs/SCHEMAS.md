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

## Planned (to be documented as implemented)

| Schema | Milestone |
|---|---|
| Error envelope `{"error": {code, message, details}}` | M1/M3 |
| `Citation`, `Warning`, `Entity`, `NotablePoint`, `VisualElement` | M2 |
| `DocumentAnalysis` (core) | M3 |
| `ConsolidatedReport` | M3 |
| `IncidentExtension` | M6 |
| `Triage` | M7 |
| `StatisticalExtension` | M8 |
