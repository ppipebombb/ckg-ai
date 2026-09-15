"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { ArrowLeft } from "lucide-react";
import { ErrorState } from "@/components/common/error-state";
import { Button } from "@/components/ui/button";
import { usePuskesmas } from "@/lib/hooks/use-puskesmas";
import { usePatient } from "@shared/patients/use-patients";
import { ScrapedDataToggle } from "./scraped-data-toggle";

// Shared patient detail shell. `actions` is the top-bar slot: frontend-internal
// passes the Rescrape/Merge action bar + Sync button; frontend-dashboard passes
// nothing, so the client view is read-only and the mutation controls never enter
// its bundle.
export function PatientDetail({
  id,
  actions,
}: {
  id: string;
  actions?: ReactNode;
}) {
  const patient = usePatient(id);
  const puskesmas = usePuskesmas(patient.data?.puskesmas_id);

  if (patient.error) return <ErrorState error={patient.error} />;

  const p = patient.data;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <Button variant="ghost" size="sm" asChild className="h-8 -ml-2 px-2">
          <Link href="/patients" prefetch={false}>
            <ArrowLeft className="h-4 w-4" />
            Kembali
          </Link>
        </Button>
        <div className="flex items-center gap-3">
          {actions}
          {p && puskesmas.data && (
            <div className="text-xs text-[var(--muted-foreground)]">
              <span className="font-medium text-[var(--foreground)]">
                {puskesmas.data.name}
              </span>
              {" • "}
              <span>{p.filter_date}</span>
            </div>
          )}
        </div>
      </div>

      {!p && (
        <div className="space-y-4">
          <div className="h-32 rounded-lg border border-[var(--border)] animate-pulse bg-[var(--muted)]" />
        </div>
      )}

      {p && (
        <ScrapedDataToggle
          patientId={id}
          fallbackName={p.nama}
          fallbackNik={p.nik}
          hasAsik={p.has_asik_data}
          hasEpus={p.has_epus_data}
          hasMerged={p.has_merged_data}
          ruangan={p.ruangan}
        />
      )}
    </div>
  );
}
