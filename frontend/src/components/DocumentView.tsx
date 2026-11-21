// Results for one document: summary, topics, entities by type, notable points,
// visual elements and warnings. Every claim carries a page chip.
import type { DocumentAnalysis } from '../api/types';
import { ENTITY_GROUPS, plural } from '../lib/labels';
import { CitationChip, Citations } from './Citations';
import { Section, WarningBanner } from './Common';
import { ModelText } from './ModelText';
import { VisualElementCard } from './VisualElementCard';

export function DocumentView({ analysis, label }: { analysis: DocumentAnalysis; label: string }) {
  const id = analysis.document_id;
  const groups = ENTITY_GROUPS.map((g) => ({
    ...g,
    items: analysis.key_entities.filter((e) => e.type === g.type),
  })).filter((g) => g.items.length > 0);

  return (
    <div className="result-view">
      <header className="result-head">
        <div>
          <p className="eyebrow">
            {label} · {plural(analysis.page_count, 'page')} · {analysis.profile} profile
          </p>
          <h2 className="result-title">{analysis.filename}</h2>
          <p className="muted">
            <ModelText text={analysis.document_type_guess} />
          </p>
        </div>
        {/* Slot for the triage badge and analyst override (M7). */}
        <div className="slot-triage" data-slot="triage" />
      </header>

      <WarningBanner warnings={analysis.warnings} documentId={id} />

      <Section title="Summary">
        <p className="lead">
          <ModelText text={analysis.summary} />
        </p>
      </Section>

      {analysis.main_topics.length > 0 && (
        <Section title="Topics">
          <p className="chips">
            {analysis.main_topics.map((t, i) => (
              <span key={i} className="chip">
                <ModelText text={t} />
              </span>
            ))}
          </p>
        </Section>
      )}

      {groups.length > 0 && (
        <Section title="Key entities" count={analysis.key_entities.length}>
          <dl className="entity-groups">
            {groups.map((g) => (
              <div key={g.type} className="entity-group">
                <dt>{g.label}</dt>
                <dd>
                  {g.items.map((e, i) => (
                    <span key={i} className="entity">
                      <ModelText text={e.name} />
                      <Citations items={e.pages.map((page) => ({ document_id: id, page }))} />
                    </span>
                  ))}
                </dd>
              </div>
            ))}
          </dl>
        </Section>
      )}

      {analysis.notable_points.length > 0 && (
        <Section title="Notable points" count={analysis.notable_points.length}>
          <ul className="points">
            {analysis.notable_points.map((p, i) => (
              <li key={i}>
                <ModelText text={p.point} />
                <CitationChip citation={{ document_id: id, page: p.page }} />
              </li>
            ))}
          </ul>
        </Section>
      )}

      {analysis.visual_elements.length > 0 && (
        <Section title="Visual elements" count={analysis.visual_elements.length}>
          <div className="visual-list">
            {analysis.visual_elements.map((v, i) => (
              <VisualElementCard key={i} element={v} documentId={id} />
            ))}
          </div>
        </Section>
      )}
    </div>
  );
}
