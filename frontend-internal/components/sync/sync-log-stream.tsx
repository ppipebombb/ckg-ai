"use client";

import { useEffect, useRef } from "react";
import { Badge } from "@/components/ui/badge";
import { useSyncStream, type StreamStatus } from "@/lib/hooks/use-sync-stream";
import { useSyncJobLog } from "@/lib/hooks/use-sync";

const STATUS_VARIANT: Record<
  StreamStatus,
  "default" | "secondary" | "destructive" | "success" | "warning" | "outline"
> = {
  idle: "outline",
  connecting: "secondary",
  streaming: "warning",
  done: "success",
  failed: "destructive",
  cancelled: "secondary",
  error: "destructive",
};

function LogBox({
  lines,
  emptyText,
  autoScroll,
}: {
  lines: string[];
  emptyText: string;
  autoScroll: boolean;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [lines.length, autoScroll]);
  return (
    <div
      ref={scrollRef}
      className="h-96 overflow-auto rounded-md border border-[var(--border)] bg-black p-3 font-mono text-xs text-emerald-300"
    >
      {lines.length === 0 ? (
        <p className="text-zinc-500">{emptyText}</p>
      ) : (
        lines.map((l, i) => (
          <div
            key={i}
            className="whitespace-pre-wrap break-all"
            style={{ contentVisibility: "auto", containIntrinsicSize: "0 16px" }}
          >
            {l}
          </div>
        ))
      )}
    </div>
  );
}

export function SyncLogStream({
  jobId,
  enabled,
}: {
  jobId: string;
  enabled: boolean;
}) {
  const { lines, status } = useSyncStream(jobId, enabled);
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">Live log</h2>
        <Badge variant={STATUS_VARIANT[status]}>{status}</Badge>
      </div>
      <LogBox lines={lines} emptyText="Waiting for output…" autoScroll />
    </div>
  );
}

export function SyncLogHistory({ jobId }: { jobId: string }) {
  const q = useSyncJobLog(jobId);
  const lines = q.data?.lines ?? [];
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">Log</h2>
        <Badge variant="outline">
          {q.isLoading ? "loading" : `${lines.length} lines`}
        </Badge>
      </div>
      <LogBox
        lines={lines}
        emptyText={q.isLoading ? "Loading…" : "No log lines"}
        autoScroll={false}
      />
    </div>
  );
}
