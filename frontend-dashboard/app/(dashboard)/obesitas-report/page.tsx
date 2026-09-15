"use client";

import { ObesitasRegistryView } from "@shared/obesitas/components/obesitas-registry-view";

export default function ObesitasReportPage() {
  // Production build: clear-cache control hidden (showClearCache={false}).
  return (
    <ObesitasRegistryView
      title="Registri Obesitas CKG"
      description="Registri Obesitas CKG: identitas, hasil pemeriksaan antropometri (BB, TB, IMT) pada tanggal berkunjung CKG, dan follow-up berat badan pada bulan kontrol (3–6 bulan setelah CKG)."
      showClearCache={false}
      exportLabel="Export Registri Obesitas CKG"
      exportFilenamePrefix="Registri Obesitas CKG"
    />
  );
}
