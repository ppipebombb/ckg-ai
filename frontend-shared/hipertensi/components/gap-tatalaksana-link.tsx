"use client";

import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useHipertensiGapListStore } from "@shared/hipertensi/hipertensi-gap-list-store";

// "Lihat Detail" on the Tertatalaksana chart card → the per-patient list behind
// the gap between its two lines. Carries the dashboard's currently-selected
// puskesmas into the Gap Tatalaksana filter store rather than a URL param, per
// CLAUDE.md §7.12 (this app keeps its SPA feel — no ?puskesmas= in the bar).
// Both apps route /hipertensi-report/gap-tatalaksana, so this stays shared.
export function GapTatalaksanaLink({ puskesmasId }: { puskesmasId: string }) {
  const setPuskesmasId = useHipertensiGapListStore((s) => s.setPuskesmasId);
  return (
    <Button
      asChild
      size="sm"
      variant="outline"
      className="h-6 shrink-0 gap-1 px-2 text-xs"
    >
      <Link
        href="/hipertensi-report/gap-tatalaksana"
        onClick={() => setPuskesmasId(puskesmasId)}
      >
        Lihat Detail
        <ArrowUpRight className="h-3 w-3" />
      </Link>
    </Button>
  );
}
