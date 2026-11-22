// Thumbs up/down on a results section. Ratings are stored to build an
// evaluation set for comparing prompt changes; they are not used for training.
import { useContext, useState } from 'react';
import { api } from '../api/client';
import type { FeedbackTarget } from '../api/types';
import { JobActionsContext } from '../lib/jobActions';

type Rating = 'up' | 'down';

export function FeedbackButtons({
  target,
  targetId,
  label,
}: {
  target: FeedbackTarget;
  targetId: string;
  /** Section name for screen readers, e.g. "Summary". */
  label: string;
}) {
  const actions = useContext(JobActionsContext);
  const [rating, setRating] = useState<Rating | null>(null);
  const [state, setState] = useState<'idle' | 'saving' | 'error'>('idle');
  if (!actions) return null; // outside a job (e.g. isolated component tests)

  const send = async (value: Rating) => {
    setState('saving');
    try {
      await api.feedback(actions.jobId, { target, target_id: targetId, rating: value });
      setRating(value);
      setState('idle');
    } catch {
      setState('error');
    }
  };

  return (
    <span className="feedback" role="group" aria-label={`Rate ${label}`}>
      {state === 'error' && <span className="feedback-error">Not saved</span>}
      {rating && state !== 'error' && <span className="feedback-thanks">Thanks</span>}
      {(['up', 'down'] as const).map((value) => (
        <button
          key={value}
          type="button"
          className={`feedback-button${rating === value ? ' is-selected' : ''}`}
          aria-pressed={rating === value}
          aria-label={value === 'up' ? `${label} is helpful` : `${label} is not helpful`}
          title={value === 'up' ? 'Helpful' : 'Not helpful'}
          disabled={state === 'saving'}
          onClick={() => void send(value)}
        >
          <span aria-hidden="true">{value === 'up' ? '👍' : '👎'}</span>
        </button>
      ))}
    </span>
  );
}
