// Suggested priority for one incident report, and the analyst's decision.
//
// The suggestion is the more severe of a rule floor (computed by code from the
// extracted facts) and a model raise that was grounded in a verbatim quote.
// Nothing is actioned automatically: the analyst confirms or overrides it, and
// an override needs a reason. The suggestion stays visible next to the decision.
import { useContext, useState, type FormEvent } from 'react';
import { ApiError, api } from '../api/client';
import type { Priority, Triage } from '../api/types';
import { JobActionsContext } from '../lib/jobActions';
import { PRIORITY_INFO, PRIORITIES } from '../lib/labels';
import { CitationChip } from './Citations';
import { RuleTag } from './IncidentSections';
import { ModelText } from './ModelText';

/** Must match MIN_REASON_CHARS in backend/app/api/jobs.py. */
export const MIN_REASON_CHARS = 5;

export function PriorityBadge({ priority, prefix }: { priority: Priority; prefix?: string }) {
  const info = PRIORITY_INFO[priority];
  return (
    <span className={`priority-badge tone-${info.tone}`} title={info.meaning}>
      {prefix && <span className="priority-prefix">{prefix}</span>}
      <strong>{priority}</strong>
      <span className="priority-label">{info.label}</span>
    </span>
  );
}

function formatTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

export function TriagePanel({ triage, documentId }: { triage: Triage; documentId: string }) {
  const actions = useContext(JobActionsContext);
  const [editing, setEditing] = useState(false);
  const [priority, setPriority] = useState<Priority>(triage.suggested_priority);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const review = triage.analyst_override;
  const modelRaised = triage.model_priority !== null;

  const submit = async (body: Parameters<typeof api.reviewTriage>[2]) => {
    if (!actions) return;
    setBusy(true);
    setError(null);
    try {
      await api.reviewTriage(actions.jobId, documentId, body);
      await actions.refresh();
      setEditing(false);
      setReason('');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'The decision could not be saved. Try again.');
    } finally {
      setBusy(false);
    }
  };

  const onOverride = (event: FormEvent) => {
    event.preventDefault();
    if (reason.trim().length < MIN_REASON_CHARS) {
      setError(`Give a reason (at least ${MIN_REASON_CHARS} characters).`);
      return;
    }
    void submit({ action: 'override', priority, reason: reason.trim() });
  };

  return (
    <section className="triage" aria-label="Triage">
      <div className="triage-head">
        <PriorityBadge priority={triage.suggested_priority} prefix="Suggested" />
        {review && (
          <>
            <span aria-hidden="true" className="triage-arrow">
              →
            </span>
            <PriorityBadge
              priority={review.priority}
              prefix={review.action === 'confirm' ? 'Confirmed' : 'Analyst'}
            />
          </>
        )}
      </div>
      <p className="triage-meta muted small">
        Confidence {triage.confidence} · rule floor {triage.rule_priority}
        {modelRaised ? ` · raised by the model to ${triage.model_priority}` : ''} ·{' '}
        <strong>needs analyst review</strong>
      </p>
      <p className="triage-rationale small">
        <ModelText text={triage.rationale} />
      </p>
      {triage.triggering_factors.length > 0 && (
        <ul className="triage-factors">
          {triage.triggering_factors.map((f, i) => (
            <li key={i}>
              {f.source === 'rule' ? (
                <RuleTag />
              ) : (
                <span className="ai-label" title="Found by the model and checked against the page text">
                  AI, quote checked
                </span>
              )}
              <ModelText text={f.factor} />
              <CitationChip citation={f.citation} />
            </li>
          ))}
        </ul>
      )}

      {review && (
        <p className="triage-review small">
          {review.action === 'confirm' ? 'Confirmed' : 'Overridden'} {formatTime(review.at)}:{' '}
          {/* Analyst-written text; rendered as plain text like everything else. */}
          <span className="triage-reason">{review.reason}</span>
        </p>
      )}

      {actions && !editing && (
        <div className="triage-actions">
          <button
            type="button"
            className="button-secondary small"
            disabled={busy}
            onClick={() => void submit({ action: 'confirm' })}
          >
            Confirm {triage.suggested_priority}
          </button>
          <button
            type="button"
            className="button-secondary small"
            disabled={busy}
            onClick={() => {
              setEditing(true);
              setError(null);
              setPriority(review?.priority ?? triage.suggested_priority);
            }}
          >
            Override…
          </button>
        </div>
      )}

      {editing && (
        <form className="triage-form" onSubmit={onOverride} noValidate>
          <label className="field">
            <span className="small">New priority</span>
            <select value={priority} onChange={(e) => setPriority(e.target.value as Priority)}>
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>
                  {p}: {PRIORITY_INFO[p].label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="small">Reason (required)</span>
            <textarea
              value={reason}
              rows={2}
              maxLength={500}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Why the priority should change"
            />
          </label>
          <div className="triage-actions">
            <button type="submit" className="button-primary small" disabled={busy}>
              Save override
            </button>
            <button
              type="button"
              className="button-secondary small"
              disabled={busy}
              onClick={() => {
                setEditing(false);
                setError(null);
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
