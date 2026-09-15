"use client";

import { useEffect, useRef } from "react";
import { Badge } from "@/components/ui/badge";
import { useLoopStream, type StreamStatus } from "@/lib/hooks/use-loop-stream";
import { useLoopRunLog } from "@/lib/hooks/use-loop";

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

type LineKind = "prose" | "tool" | "tool-error" | "warn" | "runner" | "result";

function classify(line: string): LineKind {
  const t = line.trimStart();
  if (t.startsWith("LOOP_RESULT:")) return "result";
  if (t.startsWith("[loop]") || t.startsWith("[reviewer]")) return "runner";
  if (t.startsWith("-> ")) return t.includes("[ERROR:") ? "tool-error" : "tool";
  if (t.startsWith("! ")) return "warn";
  return "prose";
}

const LINE_CLASS: Record<LineKind, string> = {
  // The agent's own words — chat bubble.
  prose:
    "my-1 rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 font-sans text-[13px] leading-relaxed whitespace-pre-wrap text-zinc-100",
  // What it did — subdued mono row.
  tool: "px-3 py-0.5 font-mono text-xs text-zinc-500 whitespace-pre-wrap",
  "tool-error": "px-3 py-0.5 font-mono text-xs text-red-400 whitespace-pre-wrap",
  warn: "px-3 py-0.5 font-mono text-xs text-amber-400 whitespace-pre-wrap",
  // The bash runner's echoes.
  runner: "px-3 py-0.5 font-mono text-xs text-sky-500 whitespace-pre-wrap",
  // Final verdict line.
  result:
    "my-2 rounded-md border border-emerald-800 bg-emerald-950/60 px-3 py-2 font-mono text-xs text-emerald-300 whitespace-pre-wrap",
};

function LogRow({ line }: { line: string }) {
  const kind = classify(line);
  const cls = LINE_CLASS[kind];
  return (
    <div
      className={cls}
      style={{ contentVisibility: "auto", containIntrinsicSize: "0 20px" }}
    >
      {kind === "tool" || kind === "tool-error" ? `▸ ${line.slice(3)}` : line}
    </div>
  );
}

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
      className="h-96 overflow-auto rounded-md border border-[var(--border)] bg-black p-3"
    >
      {lines.length === 0 ? (
        <p className="font-mono text-xs text-zinc-500">{emptyText}</p>
      ) : (
        lines
          .filter((l) => l.trim().length > 0)
          .map((l, i) => <LogRow key={i} line={l} />)
      )}
    </div>
  );
}

export function LoopLogStream({
  runId,
  enabled,
}: {
  runId: string;
  enabled: boolean;
}) {
  const { lines, status } = useLoopStream(runId, enabled);
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">Live log</h2>
        <Badge variant={STATUS_VARIANT[status]}>{status}</Badge>
      </div>
      <LogBox lines={lines} emptyText="Menunggu output agen…" autoScroll />
    </div>
  );
}

export function LoopLogHistory({ runId }: { runId: string }) {
  const q = useLoopRunLog(runId);
  const lines = q.data?.lines ?? [];
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">Log</h2>
        <Badge variant="outline">
          {q.isLoading ? "loading" : `${lines.length} baris`}
        </Badge>
      </div>
      <LogBox
        lines={lines}
        emptyText={q.isLoading ? "Memuat…" : "Tidak ada log"}
        autoScroll={false}
      />
    </div>
  );
}
