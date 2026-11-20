// Root component.
//
// M0 placeholder: shows the app shell and a one-shot backend health check so
// frontend-to-backend wiring can be verified. The polling model-status banner,
// upload panel, progress and results views arrive in M4.
import { useEffect, useState } from 'react';
import { fetchHealth, type HealthResponse } from './api/health';

type HealthState =
  | { kind: 'loading' }
  | { kind: 'ready'; health: HealthResponse }
  | { kind: 'unreachable' };

export default function App() {
  const [state, setState] = useState<HealthState>({ kind: 'loading' });

  useEffect(() => {
    const controller = new AbortController();
    fetchHealth(controller.signal)
      .then((health) => setState({ kind: 'ready', health }))
      .catch((error: unknown) => {
        // Ignore the abort triggered by unmount (and React StrictMode's double effect).
        if (error instanceof DOMException && error.name === 'AbortError') return;
        setState({ kind: 'unreachable' });
      });
    return () => controller.abort();
  }, []);

  return (
    <main className="app">
      <header>
        <h1>HTX Document Analyst</h1>
        <p className="tagline">Local AI analysis of PDF documents for analysts.</p>
      </header>
      <section aria-label="Backend status" className="status">
        {state.kind === 'loading' && <p>Checking backend…</p>}
        {state.kind === 'unreachable' && (
          <p role="alert">Backend unreachable. Is the API running?</p>
        )}
        {state.kind === 'ready' && (
          <p>
            Backend: {state.health.status} · provider {state.health.provider} · model{' '}
            {state.health.model} ({state.health.model_ready ? 'ready' : 'not ready'})
          </p>
        )}
      </section>
    </main>
  );
}
