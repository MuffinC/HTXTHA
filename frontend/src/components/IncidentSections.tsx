// Incident-profile sections of a document: ticket header, the reporter's facts
// with photo checks, consistency checks, other claims, parties and gaps.
//
// The model extracted the facts; the checks were computed by rule in the
// backend (app/pipeline/incident_rules.py). Badges always pair colour with an
// icon and text.
import type { ConsistencyCheck, IncidentExtension, SceneObservation } from '../api/types';
import { CHECK_RESULT, CORROBORATION, FACT_FIELDS, valueLabel, type Tone } from '../lib/labels';
import { CitationChip } from './Citations';
import { Section } from './Common';
import { Icon, type IconName } from './Icon';
import { ModelText } from './ModelText';

export function Badge({ tone, icon, label }: { tone: Tone; icon: IconName; label: string }) {
  return (
    <span className={`status-tag small tone-${tone}`}>
      <Icon name={icon} />
      {label}
    </span>
  );
}

export function RuleTag() {
  return (
    <span
      className="rule-tag"
      title="Computed by fixed rules from the facts the AI extracted, not written by the AI."
    >
      Rule-based
    </span>
  );
}

/** The ticket's header fields, with code-derived date and time shown and explained. */
export function TicketCard({ incident }: { incident: IncidentExtension }) {
  const { ticket, derived } = incident;
  const derivedWhen = [derived.incident_date, derived.incident_time].filter(
    (d): d is NonNullable<typeof d> => d !== null,
  );
  return (
    <section className="ticket-card" aria-label="Ticket">
      <dl className="ticket-grid">
        <div>
          <dt>Reference</dt>
          <dd className="mono">{ticket.reference_no ?? '—'}</dd>
        </div>
        <div>
          <dt>Submitted</dt>
          <dd>{ticket.submitted_at ?? '—'}</dd>
        </div>
        <div>
          <dt>Category</dt>
          <dd>
            {valueLabel(ticket.category)}{' '}
            <span className="muted small">({ticket.category_confidence} confidence)</span>
          </dd>
        </div>
        <div>
          <dt>When (as written)</dt>
          <dd>
            <ModelText text={incident.occurred_at_stated ?? 'Not stated'} />
            {derivedWhen.length > 0 && (
              <span className="derived" title={derivedWhen.map((d) => d.source).join('\n')}>
                → {derivedWhen.map((d) => d.value).join(' ')}
                {derivedWhen.some((d) => d.source.startsWith('assumed')) && ' (assumed)'}
              </span>
            )}
          </dd>
        </div>
        <div className="wide">
          <dt>Location (as written)</dt>
          <dd>
            <ModelText text={incident.location_stated ?? 'Not stated'} />
          </dd>
        </div>
      </dl>
      <p className="ticket-summary">
        <ModelText text={incident.narrative_summary} />
      </p>
    </section>
  );
}

function checkFor(incident: IncidentExtension, label: string): ConsistencyCheck | undefined {
  return incident.consistency_checks.find((c) => c.check.startsWith(`${label}:`));
}

/** The reporter's facts: quote, normalised value and how it compares with their photos. */
export function FactsTable({ incident, documentId }: { incident: IncidentExtension; documentId: string }) {
  const hasPhoto = incident.consistency_checks.length > 0;
  return (
    <Section title="Reported facts">
      <div className="table-wrap">
        <table className="facts">
          <thead>
            <tr>
              <th scope="col">Fact</th>
              <th scope="col">Reporter says</th>
              <th scope="col">Recorded as</th>
              <th scope="col">Against the photo</th>
            </tr>
          </thead>
          <tbody>
            {FACT_FIELDS.map(({ field, label }) => {
              const fact = incident.facts[field];
              const mentioned = fact.value !== 'not_mentioned';
              const check = checkFor(incident, label);
              const claim = incident.claims.find((c) => c.claim.startsWith(`${label}:`));
              const derivedLight =
                field === 'lighting' && !mentioned ? incident.derived.expected_lighting : null;
              return (
                <tr key={field} className={mentioned || derivedLight ? '' : 'is-muted'}>
                  <th scope="row">{label}</th>
                  <td>
                    {mentioned ? (
                      <>
                        <q>
                          <ModelText text={fact.as_written ?? ''} />
                        </q>
                        {fact.page !== null && (
                          <CitationChip citation={{ document_id: documentId, page: fact.page }} />
                        )}
                      </>
                    ) : derivedLight ? (
                      <span className="muted" title={derivedLight.source}>
                        Not mentioned; {valueLabel(derivedLight.value)} expected from the time
                      </span>
                    ) : (
                      <span className="muted">Not mentioned</span>
                    )}
                  </td>
                  <td>{mentioned ? valueLabel(fact.value) : '—'}</td>
                  <td>
                    {check ? (
                      <span title={check.details}>
                        <Badge {...CHECK_RESULT[check.result]} />
                      </span>
                    ) : claim ? (
                      <span title={claim.note}>
                        <Badge {...CORROBORATION[claim.corroboration]} />
                      </span>
                    ) : (
                      <span className="muted small">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {!hasPhoto && (
        <p className="muted small">No photo attached, so these facts cannot be checked against images.</p>
      )}
    </Section>
  );
}

export function IncidentDetails({
  incident,
  documentId,
}: {
  incident: IncidentExtension;
  documentId: string;
}) {
  const otherClaims = incident.claims.filter(
    (c) => !FACT_FIELDS.some(({ label }) => c.claim.startsWith(`${label}:`)),
  );
  return (
    <>
      {incident.consistency_checks.length > 0 && (
        <Section title="Narrative vs photo" count={incident.consistency_checks.length}>
          <p className="section-note">
            <RuleTag /> The reporter’s account compared with the scene fields of their own photos.
          </p>
          <ul className="checks">
            {incident.consistency_checks.map((c, i) => (
              <li key={i} className={`check tone-${CHECK_RESULT[c.result].tone}`}>
                <Badge {...CHECK_RESULT[c.result]} />
                <div>
                  <p className="check-title">
                    {c.check}
                    {c.pages.map((page) => (
                      <CitationChip key={page} citation={{ document_id: documentId, page }} />
                    ))}
                  </p>
                  <p className="muted small">
                    <ModelText text={c.details} />
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <div className="two-col">
        {otherClaims.length > 0 && (
          <Section title="Other claims" count={otherClaims.length}>
            <ul className="points">
              {otherClaims.map((c, i) => (
                <li key={i}>
                  <ModelText text={c.claim} />
                  {c.page !== null && <CitationChip citation={{ document_id: documentId, page: c.page }} />}
                  <span className="muted small"> · {CORROBORATION[c.corroboration].label}</span>
                </li>
              ))}
            </ul>
          </Section>
        )}
        {incident.parties.length > 0 && (
          <Section title="Parties (by role)" count={incident.parties.length}>
            <ul className="points">
              {incident.parties.map((p, i) => (
                <li key={i}>
                  <strong>
                    <ModelText text={p.role} />
                  </strong>{' '}
                  <span className="muted">
                    <ModelText text={p.description} />
                  </span>
                </li>
              ))}
            </ul>
          </Section>
        )}
      </div>

      {incident.missing_information.length > 0 && (
        <Section title="Missing information" count={incident.missing_information.length}>
          <ul className="points gaps">
            {incident.missing_information.map((g, i) => (
              <li key={i}>
                <ModelText text={g} />
              </li>
            ))}
          </ul>
        </Section>
      )}
    </>
  );
}

const SCENE_ROWS: { key: keyof SceneObservation; label: string }[] = [
  { key: 'lighting', label: 'Lighting' },
  { key: 'weather', label: 'Weather' },
  { key: 'road_surface', label: 'Road' },
  { key: 'vehicles_visible', label: 'Vehicles' },
  { key: 'traffic_signal', label: 'Signal' },
  { key: 'damage_locations', label: 'Damage' },
];

/** Compact grid of an incident photo's scene fields; "unclear" is muted. */
export function SceneGrid({ scene }: { scene: SceneObservation }) {
  return (
    <dl className="scene-grid" aria-label="Scene fields">
      {SCENE_ROWS.map(({ key, label }) => {
        const raw = scene[key];
        const values = Array.isArray(raw) ? raw : [raw];
        const text = values.length ? values.map((v) => valueLabel(String(v))).join(', ') : 'none';
        const unclear = values.every((v) => v === 'unclear') || text === 'none';
        return (
          <div key={key} className={unclear ? 'is-unclear' : ''}>
            <dt>{label}</dt>
            <dd>{text}</dd>
          </div>
        );
      })}
      {scene.timestamp_visible && (
        <div>
          <dt>Timestamp</dt>
          <dd className="mono">
            <ModelText text={scene.timestamp_visible} />
          </dd>
        </div>
      )}
    </dl>
  );
}
