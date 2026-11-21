// Polls GET /api/health for the model-status pill and the "backend unreachable" bar.
import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { HealthResponse } from '../api/types';

export const HEALTH_POLL_READY_MS = 10_000;
// Poll faster while the model is downloading or the backend is down, so the UI
// unlocks soon after it becomes ready.
export const HEALTH_POLL_WAITING_MS = 3_000;

export interface HealthState {
  /** Last successful response (kept while the backend is temporarily unreachable). */
  health: HealthResponse | null;
  /** false after a failed check; null before the first check completes. */
  reachable: boolean | null;
}

export function useHealth(): HealthState {
  const [state, setState] = useState<HealthState>({ health: null, reachable: null });

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;

    const check = async () => {
      let next = HEALTH_POLL_WAITING_MS;
      try {
        const health = await api.health(controller.signal);
        setState({ health, reachable: true });
        if (health.model_ready) next = HEALTH_POLL_READY_MS;
      } catch {
        if (controller.signal.aborted) return;
        setState((s) => ({ ...s, reachable: false }));
      }
      timer = setTimeout(check, next);
    };

    void check();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, []);

  return state;
}
