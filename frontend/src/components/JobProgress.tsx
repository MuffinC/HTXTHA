// Current job: overall status, a stepper per document, and an aria-live region
// that announces progress to screen readers (status is never colour-only).
import { useEffect, useState } from 'react';
import type { DocumentResult, DocumentStatus, JobResponse } from '../api/types';
import { DOCUMENT_STATUS_LABEL, REJECTION_LABEL, plural } from '../lib/labels';
import type { JobDocs } from '../lib/citations';
import { Icon } from './Icon';

const STEPS: { label: string; statuses: DocumentStatus[] }[] = [
  { label: 'Extract', statuses: ['validating', 'extracting'] },
  { label: 'Visuals', statuses: ['analysing_visuals'] },
  { label: 'Analyse', statuses: ['analysing'] },
];

function stepIndex(status: DocumentStatus): number {
  if (status === 'completed') return STEPS.length;
  if (status === 'queued') return -1;
  return STEPS.findIndex((s) => s.statuses.includes(status));
}

const JOB_STATUS_TEXT: Record<JobResponse['status'], { text: string; tone: string; icon: 'clock' | 'spinner' | 'check' | 'alert' | 'cross' }> = {
  queued: { text: 'Queued', tone: 'neutral', icon: 'clock' },
  processing: { text: 'Processing', tone: 'info', icon: 'spinner' },
  completed: { text: 'Completed', tone: 'success', icon: 'check' },
  partial: { text: 'Partly completed', tone: 'warning', icon: 'alert' },
  failed: { text: 'Failed', tone: 'danger', icon: 'cross' },
};

function DocStepper({ doc }: { doc: DocumentResult }) {
  if (doc.status === 'rejected' || doc.status === 'failed') {
    const label = doc.status === 'rejected' ? REJECTION_LABEL[doc.error?.code ?? ''] ?? 'Rejected' : 'Failed';
    return (
      <p className="doc-error">
        <Icon name="cross" /> <strong>{label}.</strong> {doc.error?.message}
      </p>
    );
  }
  const current = stepIndex(doc.status);
  return (
    <ol className="stepper" aria-label={`Progress: ${DOCUMENT_STATUS_LABEL[doc.status]}`}>
      {STEPS.map((step, i) => {
        const state = i < current ? 'done' : i === current ? 'active' : 'todo';
        return (
          <li key={step.label} className={`step is-${state}`}>
            <span className="step-dot" aria-hidden="true">
              {state === 'done' ? <Icon name="check" /> : null}
            </span>
            <span className="step-label">
              {step.label}
              <span className="visually-hidden">
                {state === 'done' ? ' (done)' : state === 'active' ? ' (in progress)' : ' (to do)'}
              </span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/** Files rejected at upload, collapsed by default when there are more than two. */
function RejectedGroup({ docs }: { docs: DocumentResult[] }) {
  const [open, setOpen] = useState(docs.length <= 2);
  return (
    <details
      className="rejected-group"
      open={open}
      onToggle={(event) => setOpen((event.target as HTMLDetailsElement).open)}
    >
      <summary>
        <Icon name="cross" />
        {plural(docs.length, 'file')} rejected at upload
      </summary>
      <ul>
        {docs.map((doc) => (
          <li key={doc.document_id}>
            <span className="file-name" title={doc.filename}>
              {doc.filename}
            </span>
            <span className="file-problem">
              <strong>{REJECTION_LABEL[doc.error?.code ?? ''] ?? 'Rejected'}.</strong>{' '}
              {doc.error?.message}
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}

function useElapsed(since: string, running: boolean): string {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [running]);
  const seconds = Math.max(0, Math.round((now - Date.parse(since)) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

/** Text for screen readers, re-announced whenever a document changes stage. */
function announcement(job: JobResponse): string {
  if (job.status === 'completed') return 'Analysis complete.';
  if (job.status === 'partial') return 'Analysis finished, but some documents failed.';
  if (job.status === 'failed') return 'Analysis failed.';
  const active = job.documents.find((d) => !['queued', 'completed', 'rejected', 'failed'].includes(d.status));
  return active ? `${active.filename}: ${DOCUMENT_STATUS_LABEL[active.status]}.` : 'Waiting to start.';
}

export function JobProgress({
  job,
  docs,
  onNew,
}: {
  job: JobResponse;
  docs: JobDocs;
  onNew: () => void;
}) {
  const running = job.status === 'queued' || job.status === 'processing';
  const elapsed = useElapsed(job.created_at, running);
  const status = JOB_STATUS_TEXT[job.status];
  const message = announcement(job);
  const processed = job.documents.filter((d) => d.status !== 'rejected');
  const rejected = job.documents.filter((d) => d.status === 'rejected');
  const done = processed.filter((d) => d.status === 'completed').length;

  return (
    <section className="panel job" aria-labelledby="job-title">
      <header className="job-head">
        <h2 id="job-title" className="panel-title">
          Current job
        </h2>
        <span className={`status-tag tone-${status.tone}`}>
          <Icon name={status.icon} className={status.icon === 'spinner' ? 'spin' : undefined} />
          {status.text}
        </span>
      </header>
      <p className="muted small job-meta">
        {done} of {plural(processed.length, 'document')} analysed
        {running ? ` · elapsed ${elapsed}` : ''}
      </p>

      <ul className="doc-progress">
        {processed.map((doc) => (
          <li key={doc.document_id}>
            <div className="doc-progress-head">
              <span className="doc-label">{docs.byId.get(doc.document_id)?.label ?? '—'}</span>
              <span className="file-name" title={doc.filename}>
                {doc.filename}
              </span>
              {doc.status === 'completed' && (
                <span className="status-tag tone-success small">
                  <Icon name="check" /> Done
                </span>
              )}
            </div>
            {doc.status !== 'completed' && <DocStepper doc={doc} />}
          </li>
        ))}
      </ul>

      {rejected.length > 0 && <RejectedGroup docs={rejected} />}

      {!running && (
        <button type="button" className="button-secondary" onClick={onNew}>
          Start a new analysis
        </button>
      )}

      <div className="visually-hidden" aria-live="polite" aria-atomic="true">
        {message}
      </div>
    </section>
  );
}
