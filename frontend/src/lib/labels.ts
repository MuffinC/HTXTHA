// Human-readable labels for codes and statuses returned by the API.
import type { DocumentStatus, EntityType, PiiCategory, VisualType, WarningCode } from '../api/types';

export type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

export const DOCUMENT_STATUS_LABEL: Record<DocumentStatus, string> = {
  queued: 'Queued',
  validating: 'Validating',
  extracting: 'Extracting text',
  analysing_visuals: 'Describing visuals',
  analysing: 'Analysing',
  completed: 'Done',
  rejected: 'Rejected',
  failed: 'Failed',
};

/** Warning title and severity. Security warnings are "danger", quality ones "warning". */
export const WARNING_INFO: Record<WarningCode, { title: string; tone: Tone; security: boolean }> = {
  INJECTION_SUSPECTED: { title: 'Possible prompt injection', tone: 'danger', security: true },
  ACTIVE_CONTENT: { title: 'Active content in PDF', tone: 'danger', security: true },
  VISUAL_PAGES_CAPPED: { title: 'Not every page was described', tone: 'warning', security: false },
  TABLE_EXTRACTION_FAILED: { title: 'Table not extracted', tone: 'warning', security: false },
  VISUAL_ANALYSIS_FAILED: { title: 'Visual analysis failed', tone: 'warning', security: false },
  CITATIONS_REMOVED: { title: 'Invalid citations removed', tone: 'warning', security: false },
  CONTENT_TRUNCATED: { title: 'Content shortened', tone: 'warning', security: false },
};

export const ENTITY_GROUPS: { type: EntityType; label: string }[] = [
  { type: 'person_role', label: 'People' },
  { type: 'organisation', label: 'Organisations' },
  { type: 'location', label: 'Locations' },
  { type: 'date_time', label: 'Dates & times' },
  { type: 'vehicle', label: 'Vehicles' },
  { type: 'object', label: 'Objects' },
  { type: 'other', label: 'Other' },
];

export const VISUAL_TYPE_LABEL: Record<VisualType, string> = {
  photo: 'Photo',
  chart: 'Chart',
  table: 'Table',
  diagram: 'Diagram',
  map: 'Map',
  scanned_text: 'Scanned text',
};

export const PII_LABEL: Record<PiiCategory, string> = {
  face: 'face',
  licence_plate: 'licence plate',
  identity_document: 'identity document',
  name: 'name',
  phone_number: 'phone number',
  address: 'address',
  signature: 'signature',
  other: 'other personal information',
};

/** Short friendly text for upload rejection codes (the backend message is shown as detail). */
export const REJECTION_LABEL: Record<string, string> = {
  UNSUPPORTED_TYPE: 'Not a PDF',
  FILE_TOO_LARGE: 'Too large',
  TOO_MANY_PAGES: 'Too many pages',
  CORRUPT_PDF: 'Damaged PDF',
  ENCRYPTED_PDF: 'Password-protected',
  EMPTY_DOCUMENT: 'No content',
  ACTIVE_CONTENT: 'Contains active content',
};

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function plural(count: number, word: string, pluralWord = `${word}s`): string {
  return `${count} ${count === 1 ? word : pluralWord}`;
}
