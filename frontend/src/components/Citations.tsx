// Citation chips ("p.3", "D2 p.1") and the page drawer they open.
//
// Every claim the AI makes cites a document and page (principle 3). Clicking a
// chip opens a side drawer for that page listing everything the analysis says
// about it. Rendered page images are not shown (M8 was skipped: DECISIONS D-069).
import { useContext, useEffect, useRef, type ReactNode } from 'react';
import type { Citation, JobResponse } from '../api/types';
import { CitationContext, type JobDocs } from '../lib/citations';
import { VISUAL_TYPE_LABEL, WARNING_INFO } from '../lib/labels';
import { Icon } from './Icon';
import { ModelText } from './ModelText';

export function CitationChip({
  citation,
  showDocument = false,
}: {
  citation: Citation;
  showDocument?: boolean;
}) {
  const ctx = useContext(CitationContext);
  const entry = ctx?.docs.byId.get(citation.document_id);
  const label = showDocument && entry ? `${entry.label} p.${citation.page}` : `p.${citation.page}`;
  const title = `Open page ${citation.page}${entry ? ` of ${entry.doc.filename}` : ''}`;
  return (
    <button
      type="button"
      className="cite"
      title={title}
      aria-label={title}
      onClick={() => ctx?.open(citation)}
    >
      {label}
    </button>
  );
}

export function Citations({ items, showDocument }: { items: Citation[]; showDocument?: boolean }) {
  return (
    <span className="cites">
      {items.map((c) => (
        <CitationChip key={`${c.document_id}:${c.page}`} citation={c} showDocument={showDocument} />
      ))}
    </span>
  );
}

// ---------------------------------------------------------------- drawer

export function PageDrawer({
  job,
  docs,
  citation,
  onClose,
}: {
  job: JobResponse;
  docs: JobDocs;
  citation: Citation;
  onClose: () => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const entry = docs.byId.get(citation.document_id);
  const analysis = entry?.doc.analysis;
  const { page } = citation;

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const cites = (list: Citation[]) =>
    list.some((c) => c.document_id === citation.document_id && c.page === page);
  const report = job.consolidated;
  const consolidatedItems: ReactNode[] = [];
  if (report) {
    report.contradictions.forEach((c, i) =>
      c.positions
        .filter((p) => cites([p.citation]))
        .forEach((p, j) =>
          consolidatedItems.push(
            <li key={`c${i}-${j}`}>
              <span className="drawer-kind">Contradiction · {c.topic}</span>
              <ModelText text={p.position} />
            </li>,
          ),
        ),
    );
    report.agreements.filter((a) => cites(a.citations)).forEach((a, i) =>
      consolidatedItems.push(
        <li key={`a${i}`}>
          <span className="drawer-kind">Agreement</span>
          <ModelText text={a.point} />
        </li>,
      ),
    );
    report.timeline.filter((e) => cites(e.citations)).forEach((e, i) =>
      consolidatedItems.push(
        <li key={`t${i}`}>
          <span className="drawer-kind">Timeline · {e.time}</span>
          <ModelText text={e.event} />
        </li>,
      ),
    );
  }

  const points = analysis?.notable_points.filter((p) => p.page === page) ?? [];
  const entities = analysis?.key_entities.filter((e) => e.pages.includes(page)) ?? [];
  const visuals = analysis?.visual_elements.filter((v) => v.page === page) ?? [];
  const warnings = analysis?.warnings.filter((w) => w.page === page) ?? [];
  const empty =
    !points.length && !entities.length && !visuals.length && !warnings.length && !consolidatedItems.length;

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="drawer-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="drawer-head">
          <div>
            <p className="eyebrow">
              {entry?.label} · {entry?.doc.filename}
            </p>
            <h2 id="drawer-title">
              Page {page}
              {analysis ? <span className="muted"> of {analysis.page_count}</span> : null}
            </h2>
          </div>
          <button ref={closeRef} type="button" className="icon-button" onClick={onClose} aria-label="Close page details">
            <Icon name="close" />
          </button>
        </header>

        <div className="page-placeholder">
          <Icon name="page" />
          <span>Page images are not shown. Open the PDF at this page to see the original; the items below cite it.</span>
        </div>

        {warnings.length > 0 && (
          <section className="drawer-section">
            <h3>Warnings on this page</h3>
            <ul>
              {warnings.map((w, i) => (
                <li key={i} className={`tone-${WARNING_INFO[w.code].tone}`}>
                  <span className="drawer-kind">{WARNING_INFO[w.code].title}</span>
                  {w.message}
                </li>
              ))}
            </ul>
          </section>
        )}
        {points.length > 0 && (
          <section className="drawer-section">
            <h3>Notable points</h3>
            <ul>
              {points.map((p, i) => (
                <li key={i}>
                  <ModelText text={p.point} />
                </li>
              ))}
            </ul>
          </section>
        )}
        {visuals.length > 0 && (
          <section className="drawer-section">
            <h3>Visual elements</h3>
            <ul>
              {visuals.map((v, i) => (
                <li key={i}>
                  <span className="drawer-kind">{VISUAL_TYPE_LABEL[v.type]}</span>
                  {v.sensitive_content.graphic ? (
                    'Graphic content: open the document tab to reveal.'
                  ) : (
                    <ModelText text={v.description} />
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}
        {entities.length > 0 && (
          <section className="drawer-section">
            <h3>Entities</h3>
            <p className="chips">
              {entities.map((e, i) => (
                <span key={i} className="chip">
                  <ModelText text={e.name} />
                </span>
              ))}
            </p>
          </section>
        )}
        {consolidatedItems.length > 0 && (
          <section className="drawer-section">
            <h3>In the consolidated report</h3>
            <ul>{consolidatedItems}</ul>
          </section>
        )}
        {empty && <p className="muted">Nothing in the analysis cites this page.</p>}
      </aside>
    </div>
  );
}
