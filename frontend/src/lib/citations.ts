// Document labels (D1, D2…) and the context that lets any citation chip open
// the page drawer. Kept out of the component files so they only export components.
import { createContext } from 'react';
import type { Citation, DocumentResult, JobResponse } from '../api/types';

export interface JobDocs {
  /** Processed (non-rejected) documents with their short label, in upload order. */
  byId: Map<string, { label: string; doc: DocumentResult }>;
}

/** D1, D2… for every document that was accepted, in upload order. */
export function labelDocuments(job: JobResponse): JobDocs {
  const byId = new Map<string, { label: string; doc: DocumentResult }>();
  let n = 0;
  for (const doc of job.documents) {
    if (doc.status === 'rejected') continue;
    n += 1;
    byId.set(doc.document_id, { label: `D${n}`, doc });
  }
  return { byId };
}

export interface CitationContextValue {
  docs: JobDocs;
  open: (citation: Citation) => void;
}

export const CitationContext = createContext<CitationContextValue | null>(null);
