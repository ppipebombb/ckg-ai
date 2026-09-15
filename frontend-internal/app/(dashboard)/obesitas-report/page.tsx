"use client";

import { ObesitasRegistryView } from "@shared/obesitas/components/obesitas-registry-view";

export default function ObesitasReportPage() {
  // Internal build: clear-cache control shown (showClearCache), so an admin can
  // force a rebuild of the 30h Redis cache without waiting for the nightly warm.
  return (
    <ObesitasRegistryView
      title="Kertas Kerja Obesitas"
      description="Registri Obesitas (format dirjen, sheet 'Obesitas'): identitas, hasil pemeriksaan antropometri (BB, TB, IMT) pada tanggal berkunjung CKG, dan follow-up berat badan pada bulan kontrol (3–6 bulan setelah CKG)."
      showClearCache
      exportLabel="Export Registri Obesitas"
      exportFilenamePrefix="Registri Obesitas"
    />
  );
}
