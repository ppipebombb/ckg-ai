"use client";

import { BayiRegistryView } from "@shared/bayi/components/bayi-registry-view";

export default function BayiKuningIkterusBeratPage() {
  return (
    <BayiRegistryView
      sheet="ikterus_berat"
      title="Registri Bayi Kuning - Ikterus Berat"
      description="Registri bayi baru lahir dengan klasifikasi 'Ikterus berat' — kuning timbul < 24 jam, atau > 14 hari, atau sampai telapak tangan/kaki."
      showClearCache={false}
      exportLabel="Export Registri Ikterus Berat"
      exportFilenamePrefix="Registri Bayi Kuning Ikterus Berat"
    />
  );
}
