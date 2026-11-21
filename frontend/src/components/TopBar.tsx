// Top bar (brand + model status) and the app-wide banners under it.
import { useState } from 'react';
import type { HealthState } from '../hooks/useHealth';
import { Icon, type IconName } from './Icon';

type PillState = { tone: string; icon: IconName; text: string; detail?: string };

function pillState({ health, reachable }: HealthState): PillState {
  if (reachable === null) return { tone: 'neutral', icon: 'clock', text: 'Checking backend…' };
  if (reachable === false) return { tone: 'danger', icon: 'plug', text: 'Backend unreachable' };
  if (!health) return { tone: 'neutral', icon: 'clock', text: 'Checking backend…' };
  if (health.provider === 'mock') {
    return { tone: 'neutral', icon: 'info', text: 'Mock provider', detail: 'no model in use' };
  }
  if (!health.model_ready) {
    return {
      tone: 'warning',
      icon: 'alert',
      text: 'Model not ready',
      detail: 'downloading, or Ollama is not running',
    };
  }
  return { tone: 'success', icon: 'check', text: 'Model ready', detail: health.model };
}

export function TopBar({ health }: { health: HealthState }) {
  const pill = pillState(health);
  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">
          <Icon name="file" />
        </span>
        <span className="brand-name">Document Analyst</span>
        <span className="brand-sub">HTX · local AI</span>
      </div>
      <div className="topbar-right">
        {health.health?.provider === 'mock' && health.reachable !== false && (
          <span className="badge badge-mock" title="Running with the mock provider">
            MOCK
          </span>
        )}
        <span className={`pill tone-${pill.tone}`} role="status" aria-live="polite">
          <Icon name={pill.icon} />
          <span>{pill.text}</span>
          {pill.detail && <span className="pill-detail">{pill.detail}</span>}
        </span>
      </div>
    </header>
  );
}

export function BackendBanner() {
  return (
    <div className="app-banner tone-danger" role="alert">
      <Icon name="plug" />
      <span>
        <strong>Can’t reach the backend.</strong> Retrying automatically. Results already shown
        stay available.
      </span>
    </div>
  );
}

export function MockStrip() {
  const [hidden, setHidden] = useState(false);
  if (hidden) return null;
  return (
    <div className="app-banner tone-neutral">
      <Icon name="info" />
      <span>
        <strong>Mock mode.</strong> Results are generated samples (marked{' '}
        <span className="mock-tag inline">MOCK</span>), not real analysis. Set <code>LLM_PROVIDER=ollama</code> to use the local model.
      </span>
      <button type="button" className="link-button" onClick={() => setHidden(true)}>
        Dismiss
      </button>
    </div>
  );
}
