"use client";

import { DmRegistryView } from "@shared/dm/components/dm-registry-view";

export default function DmReportPage() {
  // Production build: clear-cache control hidden (showClearCache={false}).
  return (
    <DmRegistryView
      title="Registri Diabetes Melitus CKG"
      description="Registri Diabetes Melitus CKG: identitas, hasil pemeriksaan gula darah pada tanggal berkunjung CKG, dan follow-up gula darah per bulan."
      showClearCache={false}
      exportLabel="Export Registri DM CKG"
      exportFilenamePrefix="Registri Diabetes Melitus CKG"
    />
  );
}
