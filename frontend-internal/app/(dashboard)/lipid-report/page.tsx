"use client";

import { LipidRegistryView } from "@shared/lipid/components/lipid-registry-view";

export default function LipidReportPage() {
  // Internal build: clear-cache control shown (showClearCache), so an admin can
  // force a rebuild of the 30h Redis cache without waiting for the nightly warm.
  return (
    <LipidRegistryView
      title="Kertas Kerja Dislipidemia"
      description="Registri Dislipidemia (format dirjen, sheet 'Dislipidemia'): identitas, hasil pemeriksaan profil lipid pada tanggal berkunjung CKG, dan follow-up profil lipid pada bulan kontrol (per 3 bulan)."
      showClearCache
      exportLabel="Export Registri Dislipidemia"
      exportFilenamePrefix="Registri Dislipidemia"
    />
  );
}
