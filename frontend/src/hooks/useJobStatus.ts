import { useCallback, useEffect, useRef, useState } from "react";

import { getJob, openJobEventStream } from "../api";
import type { JobStatus } from "../types";

export function useJobStatus() {
  const [job, setJob] = useState<JobStatus | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const streamRef = useRef<EventSource | null>(null);
  const pollRef = useRef<number | null>(null);

  const stop = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.close();
      streamRef.current = null;
    }
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const start = useCallback(
    async (jobId: string) => {
      stop();
      setJobError(null);

      const refresh = async () => {
        try {
          const latest = await getJob(jobId);
          setJob(latest);
          if (latest.status === "SUCCEEDED" || latest.status === "FAILED" || latest.status === "CANCELLED") {
            stop();
          }
        } catch (err: any) {
          setJobError(err?.response?.data?.message ?? "Unable to fetch job status");
        }
      };

      await refresh();

      const source = openJobEventStream(jobId);
      source.onmessage = () => {
        void refresh();
      };
      source.onerror = () => {
        source.close();
      };
      streamRef.current = source;

      pollRef.current = window.setInterval(() => {
        void refresh();
      }, 1500);
    },
    [stop]
  );

  useEffect(() => stop, [stop]);

  return {
    job,
    jobError,
    start,
    stop,
  };
}

