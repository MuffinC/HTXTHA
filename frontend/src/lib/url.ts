// The current job and tab live in the URL (?job=…&tab=…), so a refresh or a
// shared link reloads the same results from the API.
import { useCallback, useEffect, useState } from 'react';

export interface UrlState {
  job: string | null;
  tab: string | null;
}

function read(): UrlState {
  const params = new URLSearchParams(window.location.search);
  return { job: params.get('job'), tab: params.get('tab') };
}

function write(state: UrlState, mode: 'push' | 'replace'): void {
  const params = new URLSearchParams();
  if (state.job) params.set('job', state.job);
  if (state.job && state.tab) params.set('tab', state.tab);
  const query = params.toString();
  const url = `${window.location.pathname}${query ? `?${query}` : ''}`;
  if (mode === 'push') window.history.pushState(null, '', url);
  else window.history.replaceState(null, '', url);
}

/** Read and update ?job and ?tab. A new job is a history entry; a tab change is not. */
export function useUrlState(): {
  url: UrlState;
  setJob: (job: string | null) => void;
  setTab: (tab: string | null) => void;
} {
  const [url, setUrl] = useState<UrlState>(read);

  useEffect(() => {
    const onPop = () => setUrl(read());
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  const setJob = useCallback((job: string | null) => {
    const next = { job, tab: null };
    write(next, 'push');
    setUrl(next);
  }, []);

  const setTab = useCallback((tab: string | null) => {
    setUrl((current) => {
      const next = { ...current, tab };
      write(next, 'replace');
      return next;
    });
  }, []);

  return { url, setJob, setTab };
}
