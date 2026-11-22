// Test helper: stub window.fetch with a tiny router serving the API fixtures
// (which are real backend responses captured in mock mode; see fixtures/).
import { vi } from 'vitest';
import type {
  ConfigResponse,
  HealthResponse,
  JobCreatedResponse,
  JobResponse,
  ProfileInfo,
} from '../api/types';
import config from './fixtures/config';
import healthMock from './fixtures/healthMock';
import jobCreated from './fixtures/jobCreated';
import profiles from './fixtures/profiles';

export interface MockApiOptions {
  /** 'down' makes every request fail as if the backend were unreachable. */
  health?: HealthResponse | 'down';
  config?: ConfigResponse;
  profiles?: ProfileInfo[];
  /** Job responses by ID. An array is served in order (last one repeats): for polling. */
  jobs?: Record<string, JobResponse | JobResponse[]>;
  /** Response for POST /api/jobs: a body (202) or [status, body]. */
  createJob?: JobCreatedResponse | [number, unknown];
  /** Reply to PUT .../triage as [status, body]. Default: 200 echoing the decision. */
  triage?: [number, unknown];
  /** Reply to POST .../feedback as [status, body]. Default: 201 {id: 1}. */
  feedback?: [number, unknown];
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

export function mockApi(options: MockApiOptions = {}) {
  const served: Record<string, number> = {};
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (options.health === 'down') throw new TypeError('Failed to fetch');
    const url = typeof input === 'string' ? input : input.toString();
    const method = init?.method ?? 'GET';

    if (url === '/api/health') return json(options.health ?? healthMock);
    if (url === '/api/config') return json(options.config ?? config);
    if (url === '/api/profiles') return json(options.profiles ?? profiles);
    if (url === '/api/jobs' && method === 'POST') {
      const reply = options.createJob ?? jobCreated;
      return Array.isArray(reply) ? json(reply[1], reply[0]) : json(reply, 202);
    }
    if (/^\/api\/jobs\/[^/]+\/documents\/[^/]+\/triage$/.test(url) && method === 'PUT') {
      if (options.triage) return json(options.triage[1], options.triage[0]);
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      return json({ priority: 'P2', reason: 'Confirmed', ...body, at: '2026-01-01T09:05:00Z' });
    }
    if (/^\/api\/jobs\/[^/]+\/feedback$/.test(url) && method === 'POST') {
      const [status, body] = options.feedback ?? [201, { id: 1 }];
      return json(body, status);
    }
    const match = url.match(/^\/api\/jobs\/(.+)$/);
    if (match) {
      const id = decodeURIComponent(match[1]!);
      const entry = options.jobs?.[id];
      if (!entry) {
        return json({ error: { code: 'NOT_FOUND', message: 'No job with this ID.', details: {} } }, 404);
      }
      if (!Array.isArray(entry)) return json(entry);
      const index = Math.min(served[id] ?? 0, entry.length - 1);
      served[id] = index + 1;
      return json(entry[index]);
    }
    return json({ error: { code: 'NOT_FOUND', message: 'Unknown route', details: {} } }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

/** Put ?job=…&tab=… in the URL before rendering, as a refresh or shared link would. */
export function setUrl(params: Record<string, string>): void {
  const query = new URLSearchParams(params).toString();
  window.history.replaceState(null, '', `/${query ? `?${query}` : ''}`);
}

/** A file whose first bytes are a PDF header (passes the client-side check). */
export function pdfFile(name: string, extraBytes = 100): File {
  return new File(['%PDF-1.7\n' + 'x'.repeat(extraBytes)], name, { type: 'application/pdf' });
}
