"use client";

import { useState } from "react";
import { ErrorState } from "@/components/common/error-state";
import { EpusSourceDetail } from "./epus-source-detail";
import { AsikSourceDetail } from "./asik-source-detail";
import { MergedDataDetail } from "./merged-data-detail";
import { EpusToAsikDetail } from "./epus-to-asik-detail";
import { useDecryptedPatient } from "@shared/patients/use-patients";
import type { RawSource } from "@shared/patients/raw-patient";

type Tab = "merged" | "epus-to-asik" | RawSource;

type Props = {
  patientId: string;
  fallbackName: string;
  fallbackNik: string;
  hasAsik: boolean;
  hasEpus: boolean;
  hasMerged: boolean;
  ruangan?: string;
};

export function ScrapedDataToggle({
  patientId,
  fallbackName,
  fallbackNik,
  hasAsik,
  hasEpus,
  hasMerged,
  ruangan,
}: Props) {
  // "Epus → Asik" tab is only meaningful for epus-only patients (no real ASIK
  // record yet). Matched patients use the LLM merge instead; asik-only have
  // nothing to convert from.
  const showEpusToAsik = hasEpus && !hasAsik;

  const defaultTab: Tab = hasMerged
    ? "merged"
    : showEpusToAsik
      ? "epus-to-asik"
      : hasAsik
        ? "asik"
        : "epus";

  const [preferredTab, setPreferredTab] = useState<Tab>(defaultTab);

  const isPreferredAvailable =
    (preferredTab === "merged" && hasMerged) ||
    (preferredTab === "epus-to-asik" && showEpusToAsik) ||
    (preferredTab === "asik" && hasAsik) ||
    (preferredTab === "epus" && hasEpus);
  const tab: Tab = isPreferredAvailable ? preferredTab : defaultTab;

  const decrypted = useDecryptedPatient(
    patientId,
    hasAsik || hasEpus || hasMerged,
  );

  if (!hasAsik && !hasEpus && !hasMerged) {
    return (
      <p className="text-sm text-[var(--muted-foreground)]">
        Tidak ada data hasil scrape.
      </p>
    );
  }

  if (decrypted.isLoading) {
    return (
      <div className="space-y-3">
        <div className="h-32 rounded-lg border border-[var(--border)] animate-pulse bg-[var(--muted)]" />
        <div className="h-64 rounded-lg border border-[var(--border)] animate-pulse bg-[var(--muted)]" />
      </div>
    );
  }

  if (decrypted.error) {
    return <ErrorState error={decrypted.error} />;
  }

  if (!decrypted.data) return null;

  const toggle = (
    <div className="inline-flex rounded-lg border border-[var(--border)] p-0.5 bg-[var(--muted)]/40">
      {hasMerged && (
        <button
          type="button"
          onClick={() => setPreferredTab("merged")}
          className={
            tab === "merged"
              ? "px-4 py-1.5 text-xs font-semibold rounded-md bg-violet-600 text-white shadow-sm"
              : "px-4 py-1.5 text-xs font-semibold rounded-md text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
          }
        >
          Tergabung
        </button>
      )}
      {showEpusToAsik && (
        <button
          type="button"
          onClick={() => setPreferredTab("epus-to-asik")}
          className={
            tab === "epus-to-asik"
              ? "px-4 py-1.5 text-xs font-semibold rounded-md bg-amber-600 text-white shadow-sm"
              : "px-4 py-1.5 text-xs font-semibold rounded-md text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
          }
        >
          Epus → Asik
        </button>
      )}
      <button
        type="button"
        onClick={() => setPreferredTab("asik")}
        disabled={!hasAsik}
        className={
          tab === "asik"
            ? "px-4 py-1.5 text-xs font-semibold rounded-md bg-blue-600 text-white shadow-sm"
            : "px-4 py-1.5 text-xs font-semibold rounded-md text-[var(--muted-foreground)] hover:text-[var(--foreground)] disabled:opacity-40 disabled:cursor-not-allowed"
        }
      >
        ASIK
      </button>
      <button
        type="button"
        onClick={() => setPreferredTab("epus")}
        disabled={!hasEpus}
        className={
          tab === "epus"
            ? "px-4 py-1.5 text-xs font-semibold rounded-md bg-emerald-600 text-white shadow-sm"
            : "px-4 py-1.5 text-xs font-semibold rounded-md text-[var(--muted-foreground)] hover:text-[var(--foreground)] disabled:opacity-40 disabled:cursor-not-allowed"
        }
      >
        ePus
      </button>
    </div>
  );

  if (tab === "merged") {
    return (
      <MergedDataDetail
        rawData={decrypted.data.merged_data}
        fallbackName={fallbackName}
        fallbackNik={fallbackNik}
        filterDate={decrypted.data.filter_date}
        mergedAt={decrypted.data.merged_at}
        rightSlot={toggle}
      />
    );
  }

  if (tab === "epus-to-asik") {
    return (
      <EpusToAsikDetail
        patientId={patientId}
        fallbackName={fallbackName}
        fallbackNik={fallbackNik}
        rightSlot={toggle}
      />
    );
  }

  if (tab === "asik") {
    return (
      <AsikSourceDetail
        rawData={decrypted.data.scraped_asik_data}
        fallbackName={fallbackName}
        fallbackNik={fallbackNik}
        filterDate={decrypted.data.filter_date}
        rightSlot={toggle}
      />
    );
  }

  return (
    <EpusSourceDetail
      rawData={decrypted.data.scraped_epus_data}
      fallbackName={fallbackName}
      fallbackNik={fallbackNik}
      filterDate={decrypted.data.filter_date}
      ruangan={ruangan}
      rightSlot={toggle}
    />
  );
}
