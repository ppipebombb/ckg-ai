"use client";

import { DmRegistryView } from "@shared/dm/components/dm-registry-view";

export default function DmReportPage() {
  // Internal build: clear-cache control shown (showClearCache), so an admin can
  // force a rebuild of the 30h Redis cache without waiting for the nightly warm.
  return (
    <DmRegistryView
      title="Kertas Kerja Diabetes Melitus"
      description="Registri Diabetes Melitus (format dirjen, sheet 'Diabetes Melitus'): identitas, hasil pemeriksaan gula darah pada tanggal berkunjung CKG, dan follow-up gula darah per bulan."
      showClearCache
      exportLabel="Export Registri Diabetes Melitus"
      exportFilenamePrefix="Registri Diabetes Melitus"
    />
  );
}
