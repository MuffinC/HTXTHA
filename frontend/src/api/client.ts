// Typed client for the backend REST API (all routes under /api).
//
// Two kinds of failure are kept apart because the UI treats them differently:
//   * NetworkError: the backend could not be reached at all -> "backend unreachable".
//   * ApiError: the backend answered with its error envelope -> show code/message.
import type {
  ConfigResponse,
  ErrorEnvelope,
  HealthResponse,
  JobCreatedResponse,
  JobResponse,
  Profile,
  ProfileInfo,
} from './types';

export class NetworkError extends Error {
  constructor() {
    super('The backend could not be reached.');
    this.name = 'NetworkError';
  }
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown>) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new NetworkError();
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const envelope = body as Partial<ErrorEnvelope> | null;
    const err = envelope?.error;
    // A proxy (vite/nginx) answers 502/504 without our envelope when the backend is down.
    if (!err && response.status >= 502) throw new NetworkError();
    throw new ApiError(
      response.status,
      err?.code ?? 'HTTP_ERROR',
      err?.message ?? `Request failed with HTTP ${response.status}.`,
      err?.details ?? {},
    );
  }
  return body as T;
}

export const api = {
  health: (signal?: AbortSignal) => request<HealthResponse>('/api/health', { signal }),
  config: (signal?: AbortSignal) => request<ConfigResponse>('/api/config', { signal }),
  profiles: (signal?: AbortSignal) => request<ProfileInfo[]>('/api/profiles', { signal }),
  job: (jobId: string, signal?: AbortSignal) =>
    request<JobResponse>(`/api/jobs/${encodeURIComponent(jobId)}`, { signal }),
  createJob: (files: File[], profile: Profile) => {
    const form = new FormData();
    for (const file of files) form.append('files', file, file.name);
    form.append('profile', profile);
    return request<JobCreatedResponse>('/api/jobs', { method: 'POST', body: form });
  },
};
