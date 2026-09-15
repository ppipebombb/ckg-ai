// Glucose value formatting + interpretasi coloring for the DM registry.
//
// Lives here rather than in each app's `@/lib/` (the way hipertensi's fmtBp
// does) because it is DM-registry-specific: only the shared DM components use
// it, so a per-app copy would be exactly the duplication CLAUDE.md §11.2 warns
// about. Host-contract `@/lib/*` stays reserved for what both apps genuinely
// own independently.

/** Glucose reading → display string. HbA1C is a percentage and keeps one
 * decimal; mg/dL values are whole numbers. `null` renders as an em dash. */
export function fmtGlu(v: number | null | undefined, decimals = 0) {
  if (v == null) return "—";
  return Number.isInteger(v) && decimals === 0 ? String(v) : v.toFixed(decimals);
}

export function fmtHba1c(v: number | null | undefined) {
  return fmtGlu(v, 1);
}

/** Colour for an interpretasi label, baseline or follow-up.
 * Order matters: "tidak terkendali" must be tested before "terkendali". */
export function interpClass(v: string) {
  const s = v.toLowerCase();
  // Follow-up legend labels.
  if (s.includes("tidak terkendali")) return "bg-red-200 text-red-900";
  if (s.includes("terkendali")) return "bg-green-200 text-green-900";
  if (s.includes("missed") || s.includes("ltfu") || s.includes("loss to follow"))
    return "bg-gray-100 text-gray-700";
  // Baseline (pada tanggal berkunjung).
  if (s === "diabetes melitus") return "bg-red-200 text-red-900";
  if (s === "prediabetes") return "bg-yellow-100 text-yellow-900";
  if (s === "normal") return "bg-green-200 text-green-900";
  if (s.startsWith("tidak dapat")) return "bg-gray-100 text-gray-700";
  return "";
}
