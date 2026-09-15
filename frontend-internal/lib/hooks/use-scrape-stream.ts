"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { API_URL } from "@/lib/env";
import { readAuth } from "@/lib/auth/storage";
import { scrapeKeys } from "./use-scrape";

export type StreamStatus =
  | "idle"
  | "connecting"
  | "streaming"
  | "done"
  | "failed"
  | "cancelled"
  | "error";

const MAX_LINES = 500;

export function useScrapeStream(jobId: string | undefined, enabled: boolean) {
  const [lines, setLines] = useState<string[]>([]);
  const [status, setStatus] = useState<StreamStatus>("idle");
  const qc = useQueryClient();
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!enabled || !jobId) return;
    const auth = readAuth();
    if (!auth) return;

    // Reset ephemeral state on (re)connect — intentional sync, not a render cascade.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setStatus("connecting");
    setLines([]);

    const url = new URL(`${API_URL}/scrape/jobs/${jobId}/stream`);
    url.searchParams.set("token", auth.token);
    url.searchParams.set("backlog", "200");

    const es = new EventSource(url.toString());
    esRef.current = es;

    // Batch SSE line events into one render per animation frame: high-frequency
    // scrapes can emit hundreds of lines/sec — re-rendering per line melts CPU.
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
      qc.invalidateQueries({ queryKey: scrapeKeys.detail(jobId) });
      qc.invalidateQueries({ queryKey: scrapeKeys.lists() });
    };

    es.addEventListener("line", onLine as EventListener);
    es.addEventListener("done", () => finalize("done"));
    es.addEventListener("failed", () => finalize("failed"));
    es.addEventListener("cancelled", () => finalize("cancelled"));
    es.onerror = () => {
      // EventSource auto-reconnects on transient errors; only flag if still closed
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
