"use client";

import { useState } from "react";
import { AsyncCombobox } from "@/components/ui/async-combobox";
import {
  useAsikLocationOptions,
  packLoc,
  unpackLoc,
} from "@/lib/hooks/use-asik-locations";
import type { AsikAlamatLevel, AsikDefaultAlamat } from "@/lib/api/types";

type Sel = {
  provinsi?: AsikAlamatLevel;
  kota?: AsikAlamatLevel;
  kecamatan?: AsikAlamatLevel;
  kelurahan?: AsikAlamatLevel;
};

const ORDER: (keyof Sel)[] = ["provinsi", "kota", "kecamatan", "kelurahan"];

/**
 * 4-level Provinsi → Kota → Kecamatan → Kelurahan picker sourced from ASIK's
 * teritorial-service (so the names match the registration cascade). Emits the
 * full AsikDefaultAlamat only when all four are chosen, else null — a partial
 * address cannot be stored. Manages its own partial state; the parent form
 * remounts it (via `key`) to re-init from a puskesmas on dialog open.
 */
export function AlamatCascade({
  initialValue,
  onChange,
}: {
  initialValue: AsikDefaultAlamat | null;
  onChange: (v: AsikDefaultAlamat | null) => void;
}) {
  const [sel, setSel] = useState<Sel>(() => initialValue ?? {});

  const pick = (level: keyof Sel, id: string | undefined) => {
    const next: Sel = { ...sel, [level]: id ? unpackLoc(id) : undefined };
    // Changing an upstream level invalidates everything below it.
    for (let i = ORDER.indexOf(level) + 1; i < ORDER.length; i++) {
      next[ORDER[i]] = undefined;
    }
    setSel(next);
    onChange(
      next.provinsi && next.kota && next.kecamatan && next.kelurahan
        ? {
            provinsi: next.provinsi,
            kota: next.kota,
            kecamatan: next.kecamatan,
            kelurahan: next.kelurahan,
          }
        : null,
    );
  };

  const valOf = (l?: AsikAlamatLevel) => (l ? packLoc(l.code, l.name) : undefined);

  return (
    <div className="space-y-2">
      <AsyncCombobox
        value={valOf(sel.provinsi)}
        selectedLabel={sel.provinsi?.name}
        onChange={(id) => pick("provinsi", id)}
        useOptions={useAsikLocationOptions("province", undefined)}
        placeholder="Provinsi"
      />
      <AsyncCombobox
        value={valOf(sel.kota)}
        selectedLabel={sel.kota?.name}
        onChange={(id) => pick("kota", id)}
        useOptions={useAsikLocationOptions("city", sel.provinsi?.code)}
        placeholder="Kabupaten/Kota"
        disabled={!sel.provinsi}
      />
      <AsyncCombobox
        value={valOf(sel.kecamatan)}
        selectedLabel={sel.kecamatan?.name}
        onChange={(id) => pick("kecamatan", id)}
        useOptions={useAsikLocationOptions("district", sel.kota?.code)}
        placeholder="Kecamatan"
        disabled={!sel.kota}
      />
      <AsyncCombobox
        value={valOf(sel.kelurahan)}
        selectedLabel={sel.kelurahan?.name}
        onChange={(id) => pick("kelurahan", id)}
        useOptions={useAsikLocationOptions("subdistrict", sel.kecamatan?.code)}
        placeholder="Kelurahan/Desa"
        disabled={!sel.kecamatan}
      />
    </div>
  );
}
