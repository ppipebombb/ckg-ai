"use client";

import { BayiRegistryView } from "@shared/bayi/components/bayi-registry-view";

export default function BayiKuningIkterusPage() {
  // Internal build: clear-cache control shown so an admin can force a rebuild of
  // the 30h Redis cache without waiting for the nightly warm.
  return (
    <BayiRegistryView
      sheet="ikterus"
      title="Kertas Kerja Bayi Kuning - Ikterus"
      description="Registri bayi baru lahir dengan klasifikasi MTBM 'Ikterus' atau 'Ikterus berat' (format dirjen, sheet 'Bayi Kuning_Ikterus'): identitas, hasil pemeriksaan pada tanggal berkunjung, dan pemantauan ikterus kunjungan berikutnya."
      showClearCache
      exportLabel="Export Registri Ikterus"
      exportFilenamePrefix="Registri Bayi Kuning Ikterus"
    />
  );
}
