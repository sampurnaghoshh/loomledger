import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/api/errors";

/**
 * Load data for a page.
 *   const { data, error, loading, reload } = useApi(() => api.floor.machines(), []);
 * deps works like useEffect: change them to re-fetch.
 */
export function useApi<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const loadRef = useRef(load);
  loadRef.current = load;

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await loadRef.current());
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError("UNKNOWN", String(e)));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading, reload, setData };
}

/**
 * Run a write action (submit a form, apply a recall).
 *   const { run, running, error } = useAction((req) => api.quality.inspect(req));
 *   const result = await run(req);   // returns undefined if it failed (error is set)
 */
export function useAction<A extends unknown[], R>(action: (...args: A) => Promise<R>) {
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const run = useCallback(
    async (...args: A): Promise<R | undefined> => {
      setRunning(true);
      setError(null);
      try {
        return await action(...args);
      } catch (e) {
        setError(e instanceof ApiError ? e : new ApiError("UNKNOWN", String(e)));
        return undefined;
      } finally {
        setRunning(false);
      }
    },
    [action],
  );

  return { run, running, error, clearError: () => setError(null) };
}
