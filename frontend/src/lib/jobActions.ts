// What analyst actions need from anywhere in the results tree: the job ID, a
// way to reload the job after a change, and which view a section belongs to
// (so feedback on "Summary" is stored as document.summary or consolidated.summary).
// Kept out of component files so those only export components.
import { createContext } from 'react';

export interface JobActionsValue {
  jobId: string;
  /** Reload the job once (e.g. after a triage review) so the UI shows the stored state. */
  refresh: () => Promise<void>;
}

export const JobActionsContext = createContext<JobActionsValue | null>(null);

export type FeedbackScope = 'document' | 'consolidated';

export const FeedbackScopeContext = createContext<FeedbackScope>('document');

/** "Key entities" -> "key_entities": a stable section ID for feedback stats. */
export function sectionId(scope: FeedbackScope, title: string): string {
  const slug = title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_|_$/g, '');
  return `${scope}.${slug}`;
}
