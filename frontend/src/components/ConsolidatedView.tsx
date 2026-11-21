// The cross-document report: contradictions side by side, agreements, themes,
// timeline, related groups and gaps. Citations show the document label (D1…).
import type { ConsolidatedReport, ErrorInfo } from '../api/types';
import { useContext } from 'react';
import { CitationContext } from '../lib/citations';
import { CitationChip, Citations } from './Citations';
import { Notice, Section, WarningBanner } from './Common';
import { RuleTag } from './IncidentSections';
import { ModelText } from './ModelText';

// Mirrors backend app/pipeline/incident_rules.py (shown to the analyst, not used to compute).
const SAME_INCIDENT_WINDOW = '60-minute';
const TIME_TOLERANCE = '10 minutes';

export function ConsolidatedMissing({ error }: { error: ErrorInfo | null }) {
  if (error?.code === 'SINGLE_DOCUMENT') {
    return (
      <Notice tone="info" title="No consolidated report for this job">
        {error.message} Each document’s own analysis is in its tab.
      </Notice>
    );
  }
  return (
    <Notice tone="warning" title="The consolidated report could not be produced">
      {error?.message ?? 'It is not available.'}
    </Notice>
  );
}

function DocLabels({ ids }: { ids: string[] }) {
  const ctx = useContext(CitationContext);
  return (
    <span className="chips">
      {ids.map((id) => {
        const entry = ctx?.docs.byId.get(id);
        return (
          <span key={id} className="chip chip-doc" title={entry?.doc.filename}>
            {entry?.label ?? '?'} <span className="muted">{entry?.doc.filename}</span>
          </span>
        );
      })}
    </span>
  );
}

export function ConsolidatedView({ report, documentCount }: { report: ConsolidatedReport; documentCount: number }) {
  return (
    <div className="result-view">
      <header className="result-head">
        <div>
          <p className="eyebrow">Across {documentCount} documents</p>
          <h2 className="result-title">Consolidated report</h2>
        </div>
      </header>

      <WarningBanner warnings={report.warnings} />

      <Section title="Overall summary">
        <p className="lead">
          <ModelText text={report.overall_summary} />
        </p>
      </Section>

      {report.rule_based && (
        <Section title="Same incident" count={report.related_document_groups.length}>
          <p className="section-note">
            <RuleTag /> Grouped by category, date, a {SAME_INCIDENT_WINDOW} time window and matching
            place words.
          </p>
          {report.related_document_groups.length ? (
            <ul className="points">
              {report.related_document_groups.map((g, i) => (
                <li key={i} className="group">
                  <DocLabels ids={g.document_ids} />
                  <span className="muted small">{g.reason}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">No reports were matched to the same incident.</p>
          )}
          {report.possibly_related_groups.length > 0 && (
            <>
              <h4 className="subhead">Possibly related (check before treating as one incident)</h4>
              <ul className="points">
                {report.possibly_related_groups.map((g, i) => (
                  <li key={i} className="group">
                    <DocLabels ids={g.document_ids} />
                    <span className="muted small">{g.reason}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </Section>
      )}

      <Section title="Contradictions" count={report.contradictions.length}>
        {report.rule_based && (
          <p className="section-note">
            <RuleTag /> Compared by rule: only where two reports both state a value and the values
            differ (times more than {TIME_TOLERANCE} apart).
          </p>
        )}
        {report.contradictions.length ? (
          <div className="table-wrap">
            <table className="contradictions">
              <thead>
                <tr>
                  <th scope="col">Topic</th>
                  <th scope="col">Positions</th>
                </tr>
              </thead>
              <tbody>
                {report.contradictions.map((c, i) => (
                  <tr key={i}>
                    <th scope="row">
                      <ModelText text={c.topic} />
                    </th>
                    <td>
                      <ul className="positions">
                        {c.positions.map((p, j) => (
                          <li key={j}>
                            <CitationChip citation={p.citation} showDocument />
                            {/* Rule-based positions start with "D1: "; the chip shows it. */}
                            <ModelText text={p.position.replace(/^D\d+:\s*/, '')} />
                          </li>
                        ))}
                      </ul>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">No contradictions were found between the documents.</p>
        )}
      </Section>

      <div className="two-col">
        <Section title="Agreements" count={report.agreements.length}>
          {report.rule_based && (
            <p className="section-note">
              <RuleTag /> Every report that states the value gives the same one.
            </p>
          )}
          {report.agreements.length ? (
            <ul className="points">
              {report.agreements.map((a, i) => (
                <li key={i}>
                  <ModelText text={a.point} />
                  <Citations items={a.citations} showDocument />
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">None found.</p>
          )}
        </Section>
        <Section title="Common themes" count={report.common_themes.length}>
          {report.common_themes.length ? (
            <ul className="points">
              {report.common_themes.map((t, i) => (
                <li key={i}>
                  <ModelText text={t.theme} />
                  <Citations items={t.citations} showDocument />
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">None found.</p>
          )}
        </Section>
      </div>

      <Section title="Timeline" count={report.timeline.length}>
        {report.timeline.length ? (
          <ol className="timeline">
            {report.timeline.map((e, i) => (
              <li key={i}>
                <span className="timeline-time">
                  <ModelText text={e.time} />
                </span>
                <span className="timeline-event">
                  <ModelText text={e.event} />
                  <Citations items={e.citations} showDocument />
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="muted">No dated events.</p>
        )}
      </Section>

      <div className="two-col">
        {!report.rule_based && (
        <Section title="Related documents" count={report.related_document_groups.length}>
          {report.related_document_groups.length ? (
            <ul className="points">
              {report.related_document_groups.map((g, i) => (
                <li key={i} className="group">
                  <DocLabels ids={g.document_ids} />
                  <span>
                    <ModelText text={g.reason} />
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">No groups identified.</p>
          )}
        </Section>
        )}
        <Section title="Information gaps" count={report.information_gaps.length}>
          {report.information_gaps.length ? (
            <ul className="points">
              {report.information_gaps.map((g, i) => (
                <li key={i}>
                  <ModelText text={g} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">None noted.</p>
          )}
        </Section>
      </div>
    </div>
  );
}
