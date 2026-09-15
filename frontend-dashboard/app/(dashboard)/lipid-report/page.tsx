"use client";

import { LipidRegistryView } from "@shared/lipid/components/lipid-registry-view";

export default function LipidReportPage() {
  // Production build: clear-cache control hidden (showClearCache={false}).
  return (
    <LipidRegistryView
      title="Registri Dislipidemia CKG"
      description="Registri Dislipidemia CKG: identitas, hasil pemeriksaan profil lipid pada tanggal berkunjung CKG, dan follow-up profil lipid pada bulan kontrol (per 3 bulan)."
      showClearCache={false}
      exportLabel="Export Registri Dislipidemia CKG"
      exportFilenamePrefix="Registri Dislipidemia CKG"
    />
  );
}
