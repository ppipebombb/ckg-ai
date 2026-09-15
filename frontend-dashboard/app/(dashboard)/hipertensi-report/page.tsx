"use client";

import { HipertensiRegistryView } from "@shared/hipertensi/components/hipertensi-registry-view";

export default function HipertensiReportPage() {
  // Production build: clear-cache control hidden (showClearCache={false}).
  return (
    <HipertensiRegistryView
      title="Registri Hipertensi CKG"
      description="Registri Hipertensi CKG (V8juni2026): identitas, hasil pemeriksaan TD pada tanggal berkunjung CKG, dan follow-up tekanan darah per bulan."
      showClearCache={false}
      exportLabel="Export Registri Hipertensi CKG"
      exportFilenamePrefix="Registri Hipertensi CKG"
    />
  );
}
