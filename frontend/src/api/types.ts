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
  | 'LEADING_BYTES_IGNORED'
  | 'VISUAL_PAGES_CAPPED'
  | 'TABLE_EXTRACTION_FAILED'
  | 'VISUAL_ANALYSIS_FAILED'
  | 'VISUAL_NOT_DESCRIBED'
  | 'CITATIONS_REMOVED'
  | 'CONTENT_TRUNCATED'
  | 'INCIDENT_EXTRACTION_FAILED';

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
  /** JavaScript and launch actions. */
  active_content_policy: 'reject' | 'warn';
  /** Embedded files (attachments); never extracted. */
  embedded_file_policy: 'reject' | 'warn';
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

// ---------------------------------------------------------------- incident profile

export type Lighting = 'daylight' | 'dusk_or_dawn' | 'night_street_lit' | 'night_dark';
export type Weather = 'clear' | 'overcast' | 'rain' | 'fog';
export type RoadSurface = 'dry' | 'wet' | 'flooded';
export type VehicleType = 'car' | 'taxi' | 'motorcycle' | 'bus' | 'lorry' | 'van' | 'bicycle' | 'other';
export type DamageLocation = 'front' | 'rear' | 'left_side' | 'right_side' | 'windscreen' | 'roof';
export type VehicleCount = '1' | '2' | '3' | '4_or_more';
export type SignalState = 'red' | 'amber' | 'green';

/** Required scene fields on incident photos (the model must answer each one). */
export interface SceneObservation {
  lighting: Lighting | 'unclear';
  weather: Weather | 'unclear';
  road_surface: RoadSurface | 'unclear';
  vehicles_visible: 'none' | VehicleCount | 'unclear';
  vehicle_types: VehicleType[];
  damage_locations: (DamageLocation | 'none_visible' | 'unclear')[];
  traffic_signal: SignalState | 'not_visible' | 'unclear';
  timestamp_visible: string | null;
}

/** One fact as the reporter states it: normalised value, exact quote, page. */
export interface Stated<T extends string> {
  value: T | 'not_mentioned';
  as_written: string | null;
  page: number | null;
}

export interface IncidentFacts {
  traffic_light: Stated<SignalState | 'not_working'>;
  vehicle_count: Stated<VehicleCount>;
  weather: Stated<Weather>;
  road_surface: Stated<RoadSurface>;
  lighting: Stated<Lighting>;
  injuries: Stated<'none' | 'injury' | 'serious_or_fatal'>;
  party_left_scene: Stated<'yes' | 'no'>;
  /** Rubric P1 condition; negation is checked by code after grounding. */
  weapon: Stated<'yes' | 'no'>;
  vehicle_types: VehicleType[];
  damage_locations: DamageLocation[];
}

export type FactField = Exclude<keyof IncidentFacts, 'vehicle_types' | 'damage_locations'>;

export interface DerivedValue {
  value: string;
  source: string;
}

export interface IncidentClaim {
  claim: string;
  page: number | null;
  corroboration: 'supported' | 'contradicted' | 'not_verifiable';
  note: string;
}

export interface ConsistencyCheck {
  check: string;
  result: 'consistent' | 'inconsistent' | 'unclear';
  details: string;
  pages: number[];
}

export interface IncidentExtension {
  ticket: {
    reference_no: string | null;
    submitted_at: string | null;
    category: 'road_traffic' | 'theft' | 'fire' | 'public_disturbance' | 'other';
    category_confidence: 'low' | 'medium' | 'high';
  };
  occurred_at_stated: string | null;
  location_stated: string | null;
  narrative_summary: string;
  parties: { role: string; description: string }[];
  claims: IncidentClaim[];
  consistency_checks: ConsistencyCheck[];
  missing_information: string[];
  facts: IncidentFacts;
  derived: {
    incident_date: DerivedValue | null;
    incident_time: DerivedValue | null;
    expected_lighting: DerivedValue | null;
  };
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
  /** Incident profile, photos only. */
  scene: SceneObservation | null;
  ai_generated: true;
}

// ---------------------------------------------------------------- triage (incident profile)

export type Priority = 'P1' | 'P2' | 'P3' | 'P4';
export type Confidence = 'low' | 'medium' | 'high';

/** One reason for the priority. `source` says whether code or the model found it. */
export interface TriageFactor {
  factor: string;
  citation: Citation;
  source: 'rule' | 'model';
}

/** The analyst's decision on a suggestion: kept (confirm) or changed (override). */
export interface AnalystOverride {
  action: 'confirm' | 'override';
  priority: Priority;
  reason: string;
  at: string;
}

/**
 * Suggested priority: the more severe of the rule floor (code, from the facts)
 * and a model raise that was grounded in a verbatim quote. Never auto-actioned.
 */
export interface Triage {
  suggested_priority: Priority;
  rationale: string;
  triggering_factors: TriageFactor[];
  confidence: Confidence;
  requires_human_review: true;
  analyst_override: AnalystOverride | null;
  rule_priority: Priority;
  /** Set only when the model's raise was accepted. */
  model_priority: Priority | null;
}

export interface TriageReviewRequest {
  action: 'confirm' | 'override';
  priority?: Priority;
  reason?: string;
}

export type FeedbackTarget = 'document' | 'consolidated' | 'section';

export interface FeedbackRequest {
  target: FeedbackTarget;
  target_id: string;
  rating: 'up' | 'down';
  comment?: string;
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
  incident: IncidentExtension | null;
  /** Incident profile only. */
  triage: Triage | null;
}

// ---------------------------------------------------------------- consolidated report

export interface DocumentGroup {
  document_ids: string[];
  reason: string;
  /** Incident profile: highest member priority, lifted by safety-relevant contradictions. */
  priority?: Priority | null;
  priority_reason?: string | null;
}

export interface ConsolidatedReport {
  overall_summary: string;
  common_themes: { theme: string; citations: Citation[] }[];
  agreements: { point: string; citations: Citation[] }[];
  contradictions: { topic: string; positions: { position: string; citation: Citation }[] }[];
  timeline: { time: string; event: string; citations: Citation[] }[];
  related_document_groups: DocumentGroup[];
  information_gaps: string[];
  warnings: DocumentWarning[];
  /** Incident profile: pairs that may be the same incident (location missing/unclear). */
  possibly_related_groups: { document_ids: string[]; reason: string }[];
  /** True when contradictions, agreements, timeline and groups were computed by rule. */
  rule_based: boolean;
  /** Incident profile: code-generated count of incidents, shown above the model summary. */
  rule_summary: string | null;
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
