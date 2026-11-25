import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "./api";
import type { Job } from "./types";

export interface AsyncState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/** Load data when `deps` change; ignores responses that arrive after a newer request. */
export function useAsync<T>(load: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    let current = true;
    setLoading(true);
    setError(null);
    loadRef
      .current()
      .then((value) => {
        if (current) setData(value);
      })
      .catch((err: unknown) => {
        if (current) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [...deps, version]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  return { data, error, loading, reload };
}

const POLL_MS = 700;

/** Poll a background job until it finishes. */
export function useJob<R>(initial: Job<R> | null, onFinish?: (job: Job<R>) => void) {
  const [job, setJob] = useState<Job<R> | null>(initial);
  const [error, setError] = useState<string | null>(null);
  const finishRef = useRef(onFinish);
  finishRef.current = onFinish;
  const notified = useRef(new Set<string>());

  useEffect(() => {
    setJob(initial);
    setError(null);
  }, [initial]);

  const jobId = job?.id;
  const finished = job?.status === "done" || job?.status === "error";

  useEffect(() => {
    if (!jobId) return;
    if (finished) {
      if (job && !notified.current.has(job.id)) {
        notified.current.add(job.id);
        finishRef.current?.(job);
      }
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      api
        .job<R>(jobId)
        .then((next) => {
          if (!cancelled) setJob(next);
        })
        .catch((err: unknown) => {
          if (!cancelled) setError(err instanceof Error ? err.message : String(err));
        });
    }, POLL_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
    // Re-run on every snapshot change so polling continues while the job runs.
  }, [job, jobId, finished]);

  return { job, error };
}
