// Human-readable labels for codes and statuses returned by the API.
import type {
  ConsistencyCheck,
  DocumentStatus,
  EntityType,
  FactField,
  IncidentClaim,
  PiiCategory,
  Priority,
  VisualType,
  WarningCode,
} from "../api/types";

export type Tone = "neutral" | "info" | "success" | "warning" | "danger";

export const PRIORITIES: readonly Priority[] = ["P1", "P2", "P3", "P4"];

/** Short label and the rubric line (CLAUDE.md section 8) for each priority. */
export const PRIORITY_INFO: Record<
  Priority,
  { label: string; tone: Tone; meaning: string }
> = {
  P1: {
    label: "Urgent",
    tone: "danger",
    meaning:
      "Ongoing danger to life, serious injury or death, weapons, or a suspect at large posing a risk.",
  },
  P2: {
    label: "High",
    tone: "warning",
    meaning:
      "Injury reported, a party left the scene, significant property damage, or major contradictions needing follow-up.",
  },
  P3: {
    label: "Routine",
    tone: "info",
    meaning: "Property damage only, no injuries, parties identified.",
  },
  P4: {
    label: "Low",
    tone: "neutral",
    meaning:
      "Informational, duplicate of another report, or insufficient detail to act on.",
  },
};

/** True for items shown as notes (info tone) rather than warnings. */
export function isNote(code: WarningCode): boolean {
  return WARNING_INFO[code].tone === "info";
}

export const DOCUMENT_STATUS_LABEL: Record<DocumentStatus, string> = {
  queued: "Queued",
  validating: "Validating",
  extracting: "Extracting text",
  analysing_visuals: "Describing visuals",
  analysing: "Analysing",
  completed: "Done",
  rejected: "Rejected",
  failed: "Failed",
};

/** Warning title and severity. Security warnings are "danger", quality ones "warning". */
export const WARNING_INFO: Record<
  WarningCode,
  { title: string; tone: Tone; security: boolean }
> = {
  INJECTION_SUSPECTED: {
    title: "Possible prompt injection",
    tone: "danger",
    security: true,
  },
  ACTIVE_CONTENT: {
    title: "Active content in PDF",
    tone: "danger",
    security: true,
  },
  LEADING_BYTES_IGNORED: {
    title: "Bytes before the PDF header ignored",
    tone: "warning",
    security: false,
  },
  VISUAL_PAGES_CAPPED: {
    title: "Not every page was described",
    tone: "warning",
    security: false,
  },
  TABLE_EXTRACTION_FAILED: {
    title: "Table not extracted",
    tone: "warning",
    security: false,
  },
  VISUAL_ANALYSIS_FAILED: {
    title: "Visual analysis failed",
    tone: "warning",
    security: false,
  },
  // Info only: the page was flagged as visual but nothing was described (often a banner
  // or shaded box). Shown as a note, not a warning (DECISIONS D-076).
  VISUAL_NOT_DESCRIBED: {
    title: "No visual content described",
    tone: "info",
    security: false,
  },
  CITATIONS_REMOVED: {
    title: "Invalid citations removed",
    tone: "warning",
    security: false,
  },
  CONTENT_TRUNCATED: {
    title: "Content shortened",
    tone: "warning",
    security: false,
  },
  INCIDENT_EXTRACTION_FAILED: {
    title: "Incident facts not extracted",
    tone: "warning",
    security: false,
  },
};

export const ENTITY_GROUPS: { type: EntityType; label: string }[] = [
  { type: "person_role", label: "People" },
  { type: "organisation", label: "Organisations" },
  { type: "location", label: "Locations" },
  { type: "date_time", label: "Dates & times" },
  { type: "vehicle", label: "Vehicles" },
  { type: "object", label: "Objects" },
  { type: "other", label: "Other" },
];

export const VISUAL_TYPE_LABEL: Record<VisualType, string> = {
  photo: "Photo",
  chart: "Chart",
  table: "Table",
  diagram: "Diagram",
  map: "Map",
  scanned_text: "Scanned text",
};

export const PII_LABEL: Record<PiiCategory, string> = {
  face: "face",
  licence_plate: "licence plate",
  identity_document: "identity document",
  name: "name",
  phone_number: "phone number",
  address: "address",
  signature: "signature",
  other: "other personal information",
};

/** Short friendly text for upload rejection codes (the backend message is shown as detail). */
export const REJECTION_LABEL: Record<string, string> = {
  UNSUPPORTED_TYPE: "Not a PDF",
  FILE_TOO_LARGE: "Too large",
  TOO_MANY_PAGES: "Too many pages",
  CORRUPT_PDF: "Damaged PDF",
  ENCRYPTED_PDF: "Password-protected",
  EMPTY_DOCUMENT: "No content",
  ACTIVE_CONTENT: "Contains active content",
};

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function plural(
  count: number,
  word: string,
  pluralWord = `${word}s`,
): string {
  return `${count} ${count === 1 ? word : pluralWord}`;
}

// ---------------------------------------------------------------- incident profile

/** Fact rows, in display order. Labels match the backend's FIELD_LABELS (claims, checks). */
export const FACT_FIELDS: { field: FactField; label: string }[] = [
  { field: "traffic_light", label: "Traffic light" },
  { field: "vehicle_count", label: "Number of vehicles" },
  { field: "weather", label: "Weather" },
  { field: "road_surface", label: "Road surface" },
  { field: "lighting", label: "Lighting" },
  { field: "injuries", label: "Injuries" },
  { field: "party_left_scene", label: "A party left the scene" },
  { field: "weapon", label: "Weapon" },
];

const VALUE_LABEL: Record<string, string> = {
  "4_or_more": "4 or more",
  not_working: "not working",
  night_street_lit: "night, street lights on",
  night_dark: "night, dark",
  dusk_or_dawn: "dusk or dawn",
  serious_or_fatal: "serious or fatal",
  injury: "injury reported",
  none_visible: "none visible",
  not_visible: "not visible",
  left_side: "left side",
  right_side: "right side",
  road_traffic: "Road traffic",
  public_disturbance: "Public disturbance",
};

/** Readable form of a closed-list value from the incident schemas. */
export function valueLabel(value: string): string {
  return VALUE_LABEL[value] ?? value.replace(/_/g, " ");
}

export const CORROBORATION: Record<
  IncidentClaim["corroboration"],
  { label: string; tone: Tone; icon: "check" | "cross" | "info" }
> = {
  supported: { label: "Matches photo", tone: "success", icon: "check" },
  contradicted: { label: "Contradicts photo", tone: "danger", icon: "cross" },
  not_verifiable: { label: "Not checkable", tone: "neutral", icon: "info" },
};

export const CHECK_RESULT: Record<
  ConsistencyCheck["result"],
  { label: string; tone: Tone; icon: "check" | "cross" | "info" }
> = {
  consistent: { label: "Consistent", tone: "success", icon: "check" },
  inconsistent: { label: "Inconsistent", tone: "danger", icon: "cross" },
  unclear: { label: "Unclear", tone: "neutral", icon: "info" },
};
