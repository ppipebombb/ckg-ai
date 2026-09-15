"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { API_URL } from "@/lib/env";
import { readAuth } from "@/lib/auth/storage";
import { mergeKeys } from "./use-merge";
import { patientsKeys } from "@shared/patients/use-patients";

export type StreamStatus =
  | "idle"
  | "connecting"
  | "streaming"
  | "done"
  | "failed"
  | "cancelled"
  | "error";

const MAX_LINES = 500;

export function useMergeStream(jobId: string | undefined, enabled: boolean) {
  const [lines, setLines] = useState<string[]>([]);
  const [status, setStatus] = useState<StreamStatus>("idle");
  const qc = useQueryClient();
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!enabled || !jobId) return;
    const auth = readAuth();
    if (!auth) return;

    // eslint-disable-next-line react-hooks/set-state-in-effect
    setStatus("connecting");
    setLines([]);

    const url = new URL(`${API_URL}/merge/jobs/${jobId}/stream`);
    url.searchParams.set("token", auth.token);
    url.searchParams.set("backlog", "200");

    const es = new EventSource(url.toString());
    esRef.current = es;

    const buffer: string[] = [];
    let rafId: number | null = null;
    let streamingFlagged = false;
    const flush = () => {
      rafId = null;
      if (buffer.length === 0) return;
      const incoming = buffer.splice(0);
      setLines((prev) => {
        const next = prev.length + incoming.length > MAX_LINES
          ? prev.concat(incoming).slice(-MAX_LINES)
          : prev.concat(incoming);
        return next;
      });
    };
    const onLine = (e: MessageEvent) => {
      buffer.push(e.data);
      if (!streamingFlagged) {
        streamingFlagged = true;
        setStatus("streaming");
      }
      if (rafId == null) rafId = requestAnimationFrame(flush);
    };
    const finalize = (next: StreamStatus) => {
      if (rafId != null) {
        cancelAnimationFrame(rafId);
        rafId = null;
      }
      flush();
      setStatus(next);
      es.close();
      qc.invalidateQueries({ queryKey: mergeKeys.detail(jobId) });
      qc.invalidateQueries({ queryKey: mergeKeys.lists() });
      // Refresh patient list once on terminal — merged_at is now stale.
      qc.invalidateQueries({ queryKey: patientsKeys.lists() });
    };

    es.addEventListener("line", onLine as EventListener);
    es.addEventListener("done", () => finalize("done"));
    es.addEventListener("failed", () => finalize("failed"));
    es.addEventListener("cancelled", () => finalize("cancelled"));
    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) {
        setStatus("error");
      }
    };

    return () => {
      if (rafId != null) cancelAnimationFrame(rafId);
      es.close();
      esRef.current = null;
    };
  }, [jobId, enabled, qc]);

  return { lines, status };
}
