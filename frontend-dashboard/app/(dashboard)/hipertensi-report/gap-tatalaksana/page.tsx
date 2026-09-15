"use client";

import { GapTatalaksanaView } from "@shared/hipertensi/components/gap-tatalaksana-view";

export default function GapTatalaksanaPage() {
  return (
    <GapTatalaksanaView
      title="Gap Tatalaksana Hipertensi"
      description="Pasien hipertensi CKG yang belum pernah tercatat mendapat obat antihipertensi — selisih antara kedua garis pada grafik Pasien Hipertensi Tertatalaksana. Dilengkapi no telp dan alamat untuk ditindaklanjuti puskesmas."
    />
  );
}
