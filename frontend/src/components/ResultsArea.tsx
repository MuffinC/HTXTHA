// Right-hand results area: idle explainer, job outcome banners, result tabs
// (Consolidated | one per analysed document), and the page drawer.
import { useCallback, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import type { Citation, JobResponse } from '../api/types';
import { WARNING_INFO, plural } from '../lib/labels';
import { CitationContext, type JobDocs } from '../lib/citations';
import { PageDrawer } from './Citations';
import { Notice } from './Common';
import { ConsolidatedMissing, ConsolidatedView } from './ConsolidatedView';
import { DocumentView } from './DocumentView';
import { Icon } from './Icon';

export const CONSOLIDATED_TAB = 'consolidated';

export function EmptyState() {
  const steps = [
    ['Upload', 'One or more PDFs, such as incident reports or articles.'],
    ['Extract', 'Text, tables and pages with photos or charts are identified.'],
    ['Describe', 'Photos and charts are described: observations kept apart from inferences.'],
    ['Analyse', 'Summary, entities and notable points, each with a page reference.'],
    ['Compare', 'Agreements, contradictions and a timeline across documents.'],
  ];
  return (
    <div className="empty">
      <h2>Analyse documents locally</h2>
      <p className="muted">
        Everything runs on this machine: no document content leaves it. The AI suggests; you check
        every claim against its cited page.
      </p>
      <ol className="how">
        {steps.map(([title, text], i) => (
          <li key={title}>
            <span className="how-num">{i + 1}</span>
            <div>
              <p className="how-title">{title}</p>
              <p className="muted small">{text}</p>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

function OutcomeBanner({ job }: { job: JobResponse }) {
  const processed = job.documents.filter((d) => d.status !== 'rejected');
  const failed = processed.filter((d) => d.status === 'failed');
  const rejected = job.documents.filter((d) => d.status === 'rejected');
  if (job.status === 'failed') {
    return (
      <Notice tone="danger" title="The analysis failed" role="alert">
        <p>{job.error?.message}</p>
        {failed.length > 0 && (
          <ul className="plain-list">
            {failed.map((d) => (
              <li key={d.document_id}>
                <strong>{d.filename}</strong>: {d.error?.message}
              </li>
            ))}
          </ul>
        )}
      </Notice>
    );
  }
  if (job.status === 'partial') {
    const done = processed.length - failed.length;
    return (
      <Notice tone="warning" title={`${done} of ${plural(processed.length, 'document')} analysed`} role="status">
        {failed.length > 0 ? (
          <ul className="plain-list">
            {failed.map((d) => (
              <li key={d.document_id}>
                <strong>{d.filename}</strong> failed: {d.error?.message}
              </li>
            ))}
          </ul>
        ) : (
          <p>{job.consolidated_error?.message}</p>
        )}
        {rejected.length > 0 && (
          <p className="muted small">{plural(rejected.length, 'file')} rejected at upload (see the job panel).</p>
        )}
      </Notice>
    );
  }
  return null;
}

export function ResultsArea({
  job,
  docs,
  tab,
  onTab,
}: {
  job: JobResponse;
  docs: JobDocs;
  tab: string | null;
  onTab: (tab: string) => void;
}) {
  const [drawer, setDrawer] = useState<Citation | null>(null);
  const open = useCallback((c: Citation) => setDrawer(c), []);
  const close = useCallback(() => setDrawer(null), []);
  const context = useMemo(() => ({ docs, open }), [docs, open]);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const completed = job.documents.filter((d) => d.status === 'completed' && d.analysis);
  const processedCount = [...docs.byId.values()].length;
  const running = job.status === 'queued' || job.status === 'processing';
  // The consolidated tab appears once there is something to look at: a finished
  // document, or a finished job (whose tab then explains any missing report).
  const showConsolidated =
    (processedCount > 1 || job.consolidated !== null) && (completed.length > 0 || !running);

  const tabs = [
    ...(showConsolidated ? [{ id: CONSOLIDATED_TAB, label: 'Consolidated report', warnings: 0, security: false }] : []),
    ...completed.map((d) => {
      const warnings = d.analysis?.warnings ?? [];
      return {
        id: d.document_id,
        label: `${docs.byId.get(d.document_id)?.label} ${d.filename}`,
        warnings: warnings.length,
        security: warnings.some((w) => WARNING_INFO[w.code].security),
      };
    }),
  ];

  const defaultTab = job.consolidated ? CONSOLIDATED_TAB : (completed[0]?.document_id ?? tabs[0]?.id);
  const active = tabs.some((t) => t.id === tab) ? tab : defaultTab;
  const activeDoc = completed.find((d) => d.document_id === active);

  const onKeyDown = (event: KeyboardEvent, index: number) => {
    const delta = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
    if (!delta) return;
    const next = (index + delta + tabs.length) % tabs.length;
    onTab(tabs[next]!.id);
    tabRefs.current[next]?.focus();
  };

  return (
    <CitationContext.Provider value={context}>
      <OutcomeBanner job={job} />
      {tabs.length > 0 ? (
        <>
          <div className="tabs" role="tablist" aria-label="Results">
            {tabs.map((t, i) => (
              <button
                key={t.id}
                ref={(el) => {
                  tabRefs.current[i] = el;
                }}
                type="button"
                role="tab"
                id={`tab-${t.id}`}
                aria-selected={t.id === active}
                aria-controls="result-panel"
                tabIndex={t.id === active ? 0 : -1}
                className="tab"
                onClick={() => onTab(t.id)}
                onKeyDown={(e) => onKeyDown(e, i)}
              >
                <span className="tab-label">{t.label}</span>
                {t.warnings > 0 && (
                  <span className={`tab-warn tone-${t.security ? 'danger' : 'warning'}`} title={plural(t.warnings, 'warning')}>
                    <Icon name={t.security ? 'shield' : 'alert'} />
                    {t.warnings}
                    <span className="visually-hidden"> {plural(t.warnings, 'warning')}</span>
                  </span>
                )}
              </button>
            ))}
          </div>
          <div className="tab-panel" role="tabpanel" id="result-panel" aria-labelledby={`tab-${active}`}>
            {active === CONSOLIDATED_TAB ? (
              job.consolidated ? (
                <ConsolidatedView report={job.consolidated} documentCount={completed.length} />
              ) : running ? (
                <Notice tone="info" title="Consolidated report pending" icon="clock">
                  It is built once every document has been analysed.
                </Notice>
              ) : (
                <ConsolidatedMissing error={job.consolidated_error} />
              )
            ) : activeDoc?.analysis ? (
              <DocumentView
                analysis={activeDoc.analysis}
                label={docs.byId.get(activeDoc.document_id)?.label ?? ''}
              />
            ) : null}
          </div>
        </>
      ) : running ? (
        <div className="empty">
          <Icon name="spinner" className="spin large" />
          <p className="muted">Results appear here as each document is analysed.</p>
        </div>
      ) : null}
      {drawer && <PageDrawer job={job} docs={docs} citation={drawer} onClose={close} />}
    </CitationContext.Provider>
  );
}
