import { cn } from "@/lib/utils";
import type { WarmProgress as WarmProgressData } from "@/lib/api/warm-progress";

/**
 * Determinate progress bar for a background report warm (first-compute /
 * cold-cache). Fed by the `progress` field on a `computing` response. When
 * `progress` is absent (first poll, before the scan's first tick) it degrades to
 * a label + indeterminate pulsing bar, so "Menghitung…" is never silent again.
 *
 * The percentage is approximate (patients decrypted / total) — see WarmProgress
 * on the backend.
 */
export function WarmProgress({
  progress,
  label = "Menghitung…",
  className,
}: {
  progress?: WarmProgressData | null;
  label?: string | null;
  className?: string;
}) {
  const pct =
    progress && progress.total > 0
      ? Math.min(100, Math.round((progress.done / progress.total) * 100))
      : null;

  return (
    <div className={cn("w-full max-w-sm space-y-1.5", className)}>
      {(label || pct !== null) && (
        <div className="flex items-center justify-between text-sm text-[var(--muted-foreground)]">
          <span>{label}</span>
          {pct !== null && (
            <span className="tabular-nums">
              {progress!.done.toLocaleString("id-ID")}/
              {progress!.total.toLocaleString("id-ID")} · {pct}%
            </span>
          )}
        </div>
      )}
      <div
        className="h-2 w-full overflow-hidden rounded-full bg-[var(--muted)]"
        role="progressbar"
        aria-valuenow={pct ?? undefined}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className={cn(
            "h-full rounded-full bg-[var(--primary)] transition-[width] duration-700 ease-out",
            pct === null && "w-1/3 animate-pulse",
          )}
          style={pct !== null ? { width: `${pct}%` } : undefined}
        />
      </div>
    </div>
  );
}
