// Typed client for GET /api/health. Mirrors backend/app/api/health.py.

export interface HealthResponse {
  status: 'ok' | 'degraded';
  provider: 'ollama' | 'mock';
  model: string;
  model_ready: boolean;
}

/**
 * Fetch backend health. Throws if the backend is unreachable or replies with
 * a non-2xx status, so callers can show a "backend unreachable" state.
 */
export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch('/api/health', { signal });
  if (!response.ok) {
    throw new Error(`Health check failed with HTTP ${response.status}`);
  }
  return (await response.json()) as HealthResponse;
}
