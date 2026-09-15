"use client";

import { BayiRegistryView } from "@shared/bayi/components/bayi-registry-view";

export default function BayiKuningIkterusPage() {
  // Production build: clear-cache control hidden.
  return (
    <BayiRegistryView
      sheet="ikterus"
      title="Registri Bayi Kuning - Ikterus"
      description="Registri bayi baru lahir dengan klasifikasi 'Ikterus' atau 'Ikterus berat': identitas, hasil pemeriksaan pada tanggal berkunjung, dan pemantauan ikterus kunjungan berikutnya."
      showClearCache={false}
      exportLabel="Export Registri Ikterus"
      exportFilenamePrefix="Registri Bayi Kuning Ikterus"
    />
  );
}
