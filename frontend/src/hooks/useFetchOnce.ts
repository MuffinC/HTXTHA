// Fetch something that rarely changes (config, profiles) once, retrying until it succeeds.
import { useEffect, useState } from 'react';

export const FETCH_RETRY_MS = 5_000;

export function useFetchOnce<T>(load: (signal: AbortSignal) => Promise<T>): T | null {
  const [value, setValue] = useState<T | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const attempt = () => {
      load(controller.signal)
        .then(setValue)
        .catch(() => {
          // Backend not up yet: the health bar already says so; just try again.
          if (!controller.signal.aborted) timer = setTimeout(attempt, FETCH_RETRY_MS);
        });
    };
    attempt();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
    // `load` is a stable module-level function at every call site.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return value;
}
