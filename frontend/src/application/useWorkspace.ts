import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { JobEvent, OcrJob } from "../domain/ocr";
import { isActiveJob, mergeJobEvent } from "../domain/ocr";
import { getApiKey, subscribeApiKey } from "../infrastructure/auth/apiKeyStore";
import { getJob, listJobs } from "../infrastructure/api/jobs";
import { subscribeJobEvents } from "../infrastructure/api/sse";

export function useSessionApiKey(): string | null {
  return useSyncExternalStore(subscribeApiKey, getApiKey, () => null);
}

function newestFirst(jobs: OcrJob[]): OcrJob[] {
  return [...jobs].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
}

export function useJobs(enabled: boolean) {
  const [jobs, setJobs] = useState<OcrJob[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const upsertJob = useCallback((next: OcrJob) => {
    setJobs((current) => {
      const index = current.findIndex((job) => job.job_id === next.job_id);
      if (index === -1) return newestFirst([next, ...current]);
      const copy = [...current];
      copy[index] = next;
      return newestFirst(copy);
    });
  }, []);

  const updateFromEvent = useCallback((event: JobEvent) => {
    setJobs((current) =>
      current.map((job) => (job.job_id === event.job_id ? mergeJobEvent(job, event) : job)),
    );
  }, []);

  const refresh = useCallback(async () => {
    if (!enabled) return;
    setLoading(true);
    try {
      const result = await listJobs();
      setJobs(newestFirst(result.items));
      setError(null);
    } catch (nextError) {
      setError(nextError);
    } finally {
      setLoading(false);
    }
  }, [enabled]);

  const refreshJob = useCallback(
    async (jobId: string) => {
      if (!enabled) return;
      try {
        upsertJob(await getJob(jobId));
        setError(null);
      } catch (nextError) {
        setError(nextError);
      }
    },
    [enabled, upsertJob],
  );

  useEffect(() => {
    if (!enabled) {
      setJobs([]);
      return;
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), 20_000);
    return () => window.clearInterval(timer);
  }, [enabled, refresh]);

  return { jobs, loading, error, setError, refresh, refreshJob, upsertJob, updateFromEvent };
}

export type LiveConnection = "idle" | "connecting" | "open" | "reconnecting";

export function useJobSubscription(
  job: OcrJob | undefined,
  onEvent: (event: JobEvent) => void,
  onFallbackPoll: (jobId: string) => void,
): LiveConnection {
  const [connection, setConnection] = useState<LiveConnection>("idle");
  const eventHandler = useRef(onEvent);
  const pollHandler = useRef(onFallbackPoll);
  const lastEventIds = useRef(new Map<string, string>());
  eventHandler.current = onEvent;
  pollHandler.current = onFallbackPoll;
  const active = Boolean(job && isActiveJob(job.status));

  useEffect(() => {
    if (!job || !active) {
      setConnection("idle");
      return;
    }

    let pollingTimer: number | undefined;
    const subscription = subscribeJobEvents(job.job_id, {
      lastEventId: lastEventIds.current.get(job.job_id),
      onEvent: (event, eventId) => {
        if (eventId) lastEventIds.current.set(job.job_id, eventId);
        eventHandler.current(event);
      },
      onConnectionChange: (state) => {
        if (state === "closed") {
          setConnection("idle");
          pollHandler.current(job.job_id);
          return;
        }
        setConnection(state);
        if (state === "open" && pollingTimer) {
          window.clearInterval(pollingTimer);
          pollingTimer = undefined;
        }
        if (state === "reconnecting" && !pollingTimer) {
          const configuredPoll = Number(import.meta.env.VITE_JOB_POLL_INTERVAL_MS || 5_000);
          const pollInterval = Number.isFinite(configuredPoll)
            ? Math.max(1_000, configuredPoll)
            : 5_000;
          pollHandler.current(job.job_id);
          pollingTimer = window.setInterval(() => pollHandler.current(job.job_id), pollInterval);
        }
      },
      onError: () => undefined,
    });

    return () => {
      const lastEventId = subscription.getLastEventId();
      if (lastEventId) lastEventIds.current.set(job.job_id, lastEventId);
      subscription.close();
      if (pollingTimer) window.clearInterval(pollingTimer);
    };
  }, [job?.job_id, active]);

  return connection;
}
