// Polls GET /api/jobs/{id} every 2 s until the job reaches a final status
// (CLAUDE.md section 10). Network failures keep the last result on screen and
// retry with backoff, so a backend blip never blanks the page.
import { useEffect, useState } from 'react';
import { ApiError, api } from '../api/client';
import { FINAL_JOB_STATUSES, type JobResponse } from '../api/types';

export const JOB_POLL_MS = 2_000;
export const JOB_POLL_MAX_BACKOFF_MS = 10_000;

export interface JobState {
  job: JobResponse | null;
  /** "not_found": the ID is unknown (404). "unreachable": the last poll could not connect. */
  problem: 'not_found' | 'unreachable' | null;
}

export function useJob(jobId: string | null): JobState {
  const [state, setState] = useState<JobState>({ job: null, problem: null });

  useEffect(() => {
    setState({ job: null, problem: null });
    if (!jobId) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let delay = JOB_POLL_MS;

    const poll = async () => {
      try {
        const job = await api.job(jobId, controller.signal);
        setState({ job, problem: null });
        delay = JOB_POLL_MS;
        if (FINAL_JOB_STATUSES.includes(job.status)) return; // stop polling
      } catch (error) {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 404) {
          setState({ job: null, problem: 'not_found' });
          return;
        }
        setState((s) => ({ ...s, problem: 'unreachable' }));
        delay = Math.min(delay * 2, JOB_POLL_MAX_BACKOFF_MS);
      }
      timer = setTimeout(poll, delay);
    };

    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [jobId]);

  return state;
}
