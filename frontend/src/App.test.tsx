import { render, screen } from '@testing-library/react';
import { vi } from 'vitest';
import App from './App';
import type { HealthResponse } from './api/health';

function stubFetchOk(body: HealthResponse) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 200 })),
  );
}

describe('App', () => {
  it('renders the title and backend health when reachable', async () => {
    stubFetchOk({ status: 'ok', provider: 'mock', model: 'mock', model_ready: true });

    render(<App />);

    expect(screen.getByRole('heading', { name: 'HTX Document Analyst' })).toBeInTheDocument();
    expect(await screen.findByText(/Backend: ok/)).toBeInTheDocument();
    expect(screen.getByText(/\(ready\)/)).toBeInTheDocument();
  });

  it('shows an unreachable message when the backend is down', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));

    render(<App />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Backend unreachable');
  });
});
