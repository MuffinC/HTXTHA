// TypeScript mirror of the backend's API schemas (backend/app/schemas/*, docs/SCHEMAS.md).
//
// Hand-written on purpose (no code generator dependency). They are checked
// against real API output: the frontend tests load fixtures captured from the
// running backend in mock mode (backend/tests/test_frontend_fixtures.py), and
// that backend test fails if the API output drifts from the committed fixtures.

// ---------------------------------------------------------------- shared

export type Profile = 'general' | 'incident' | 'statistical';

export interface Citation {
  document_id: string;
  page: number;
}

export type WarningCode =
  | 'INJECTION_SUSPECTED'
  | 'ACTIVE_CONTENT'
  | 'VISUAL_PAGES_CAPPED'
  | 'TABLE_EXTRACTION_FAILED'
  | 'VISUAL_ANALYSIS_FAILED'
  | 'CITATIONS_REMOVED'
  | 'CONTENT_TRUNCATED';

export interface DocumentWarning {
  code: WarningCode;
  message: string;
  page: number | null;
}

/** Why a job or document failed. `message` is written by the backend, never the model. */
export interface ErrorInfo {
  code: string;
  message: string;
}

// ---------------------------------------------------------------- health, config, profiles

export interface HealthResponse {
  status: 'ok' | 'degraded';
  provider: 'ollama' | 'mock';
  model: string;
  model_ready: boolean;
}

export interface ConfigResponse {
  max_files: number;
  max_file_mb: number;
  max_pages: number;
  max_visual_pages_per_doc: number;
  active_content_policy: 'reject' | 'warn';
  mask_pii: boolean;
  retain_uploads: boolean;
}

export interface ProfileInfo {
  id: Profile;
  name: string;
  description: string;
  available: boolean;
}

// ---------------------------------------------------------------- visual analysis

export type VisualType = 'photo' | 'chart' | 'table' | 'diagram' | 'map' | 'scanned_text';

export type PiiCategory =
  | 'face'
  | 'licence_plate'
  | 'identity_document'
  | 'name'
  | 'phone_number'
  | 'address'
  | 'signature'
  | 'other';

export interface Inference {
  inference: string;
  basis: string;
}

export interface ChartDetails {
  chart_type: string;
  x_axis: string;
  y_axis: string;
  key_values: string[];
  trend: string;
}

export interface VisualElement {
  page: number;
  type: VisualType;
  description: string;
  observations: string[];
  possible_inferences: Inference[];
  information_gaps: string[];
  table_markdown: string | null;
  chart: ChartDetails | null;
  transcription: string | null;
  sensitive_content: { graphic: boolean; pii_visible: PiiCategory[] };
  ai_generated: true;
}

// ---------------------------------------------------------------- document analysis

export type EntityType =
  | 'person_role'
  | 'organisation'
  | 'location'
  | 'date_time'
  | 'vehicle'
  | 'object'
  | 'other';

export interface Entity {
  name: string;
  type: EntityType;
  pages: number[];
}

export interface NotablePoint {
  point: string;
  page: number;
}

export interface DocumentAnalysis {
  document_id: string;
  filename: string;
  page_count: number;
  profile: Profile;
  document_type_guess: string;
  summary: string;
  main_topics: string[];
  key_entities: Entity[];
  notable_points: NotablePoint[];
  visual_elements: VisualElement[];
  warnings: DocumentWarning[];
}

// ---------------------------------------------------------------- consolidated report

export interface ConsolidatedReport {
  overall_summary: string;
  common_themes: { theme: string; citations: Citation[] }[];
  agreements: { point: string; citations: Citation[] }[];
  contradictions: { topic: string; positions: { position: string; citation: Citation }[] }[];
  timeline: { time: string; event: string; citations: Citation[] }[];
  related_document_groups: { document_ids: string[]; reason: string }[];
  information_gaps: string[];
  warnings: DocumentWarning[];
}

// ---------------------------------------------------------------- jobs

export type JobStatus = 'queued' | 'processing' | 'completed' | 'partial' | 'failed';

export type DocumentStatus =
  | 'queued'
  | 'validating'
  | 'extracting'
  | 'analysing_visuals'
  | 'analysing'
  | 'completed'
  | 'rejected'
  | 'failed';

export const FINAL_JOB_STATUSES: readonly JobStatus[] = ['completed', 'partial', 'failed'];

export interface RejectedFile {
  filename: string;
  code: string;
  message: string;
}

export interface AcceptedDocument {
  document_id: string;
  filename: string;
  page_count: number;
  warnings: DocumentWarning[];
}

export interface JobCreatedResponse {
  job_id: string;
  accepted: AcceptedDocument[];
  rejected: RejectedFile[];
}

export interface DocumentResult {
  document_id: string;
  filename: string;
  status: DocumentStatus;
  page_count: number | null;
  error: ErrorInfo | null;
  analysis: DocumentAnalysis | null;
}

export interface JobResponse {
  job_id: string;
  profile: Profile;
  status: JobStatus;
  created_at: string;
  updated_at: string;
  error: ErrorInfo | null;
  documents: DocumentResult[];
  consolidated: ConsolidatedReport | null;
  consolidated_error: ErrorInfo | null;
}

// ---------------------------------------------------------------- errors

/** The backend's error envelope (every non-2xx response). */
export interface ErrorEnvelope {
  error: { code: string; message: string; details: Record<string, unknown> };
}
