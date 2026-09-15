// Lipid value formatting + interpretasi coloring for the Dislipidemia registry.
//
// Lives here rather than in each app's `@/lib/` (the way hipertensi's fmtBp
// does) because it is Dislipidemia-registry-specific: only the shared lipid
// components use it, so a per-app copy would be exactly the duplication
// CLAUDE.md §11.2 warns about. Host-contract `@/lib/*` stays reserved for what
// both apps genuinely own independently.

/** Lipid reading → display string. All four analytes (Kolesterol Total, LDL,
 * HDL, Trigliserida) are mg/dL and are reported as whole numbers. `null`
 * renders as an em dash. */
export function fmtLipid(v: number | null | undefined) {
  if (v == null) return "—";
  return Number.isInteger(v) ? String(v) : v.toFixed(0);
}

/** Colour for an interpretasi label, baseline or follow-up.
 * Order matters: "tidak terkendali" must be tested before "terkendali". */
export function interpClass(v: string) {
  const s = v.toLowerCase();
  // Follow-up legend labels (N17).
  if (s.includes("tidak terkendali")) return "bg-red-200 text-red-900";
  if (s.includes("terkendali")) return "bg-green-200 text-green-900";
  if (s.includes("missed") || s.includes("ltfu") || s.includes("loss to follow"))
    return "bg-gray-100 text-gray-700";
  // Baseline (pada tanggal berkunjung). No middle band exists for this sheet —
  // it defines one threshold per analyte, not a borderline range, so there is
  // no "Pre-Hipertensi"/"Prediabetes" equivalent to colour here.
  if (s === "dislipidemia") return "bg-red-200 text-red-900";
  if (s === "normal") return "bg-green-200 text-green-900";
  return "";
}
