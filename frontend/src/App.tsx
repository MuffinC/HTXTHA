// Root component: wires health, config, profiles, the URL-held job and polling
// to the layout (top bar; upload + progress on the left; results on the right).
//
// State is kept deliberately simple: the URL (?job, ?tab) is the source of
// truth for which job is shown, and the backend is the source of truth for
// everything about that job.
import { useMemo } from 'react';
import { api } from './api/client';
import type { JobCreatedResponse } from './api/types';
import { labelDocuments } from './lib/citations';
import { Notice } from './components/Common';
import { JobProgress } from './components/JobProgress';
import { EmptyState, ResultsArea } from './components/ResultsArea';
import { BackendBanner, MockStrip, TopBar } from './components/TopBar';
import { UploadPanel } from './components/UploadPanel';
import { useFetchOnce } from './hooks/useFetchOnce';
import { useHealth } from './hooks/useHealth';
import { useJob } from './hooks/useJob';
import { useUrlState } from './lib/url';

export default function App() {
  const health = useHealth();
  const config = useFetchOnce(api.config);
  const profiles = useFetchOnce(api.profiles);
  const { url, setJob, setTab } = useUrlState();
  const { job, problem } = useJob(url.job);
  const docs = useMemo(() => (job ? labelDocuments(job) : { byId: new Map() }), [job]);

  const unreachable = health.reachable === false || problem === 'unreachable';
  const isMock = health.health?.provider === 'mock';
  const running = job?.status === 'queued' || job?.status === 'processing';

  let blockedReason: string | null = null;
  if (unreachable) blockedReason = 'The backend is unreachable.';
  else if (health.health && !health.health.model_ready)
    blockedReason = 'The model is not ready yet (downloading, or Ollama is not running).';
  else if (running) blockedReason = 'Wait for the current job to finish.';

  const onCreated = (response: JobCreatedResponse) => setJob(response.job_id);

  return (
    <div className="app">
      <TopBar health={health} />
      {unreachable && <BackendBanner />}
      {isMock && !unreachable && <MockStrip />}

      <div className="layout">
        <aside className="sidebar" aria-label="Upload and progress">
          <UploadPanel
            config={config}
            profiles={profiles}
            blockedReason={blockedReason}
            onCreated={onCreated}
          />
          {job && <JobProgress job={job} docs={docs} onNew={() => setJob(null)} />}
        </aside>

        <main className="results" aria-label="Results">
          {problem === 'not_found' ? (
            <Notice
              tone="warning"
              title="Job not found"
              action={
                <button type="button" className="button-secondary" onClick={() => setJob(null)}>
                  Start a new analysis
                </button>
              }
            >
              The job in this link does not exist on this backend. It may have been created on
              another machine, or the database was reset.
            </Notice>
          ) : job ? (
            <ResultsArea job={job} docs={docs} tab={url.tab} onTab={setTab} />
          ) : url.job && unreachable ? (
            <Notice tone="neutral" icon="plug" title="Waiting for the backend">
              This job’s results will load as soon as the backend can be reached again.
            </Notice>
          ) : url.job ? (
            <p className="muted">Loading job…</p>
          ) : (
            <EmptyState />
          )}
        </main>
      </div>
    </div>
  );
}
