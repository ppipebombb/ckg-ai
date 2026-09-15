// Anthropometry formatting + interpretasi coloring for the Obesitas registry.
//
// Lives here rather than in each app's `@/lib/` for the same reason
// frontend-shared/lipid/format.ts does: it is Obesitas-registry-specific, so a
// per-app copy would be exactly the duplication CLAUDE.md §11.2 warns about.

/** Weight (kg) or height (cm) → display string. `null` renders as an em dash.
 * Trailing zeros are dropped rather than padded: ePuskesmas records a weight as
 * "78" far more often than "78.0", and padding makes the column look more
 * precise than the source is. */
export function fmtAntro(v: number | null | undefined) {
  if (v == null) return "—";
  return String(Math.round(v * 10) / 10);
}

/** IMT → display string, always 1 decimal — the precision the dirjen sheet's own
 * bands are written at ("IMT 25-29.9"), and the precision the backend rounds to
 * before classifying. Showing more digits would let a row read "24.97 / Obesitas
 * I" at the boundary. */
export function fmtImt(v: number | null | undefined) {
  if (v == null) return "—";
  return v.toFixed(1);
}

/** Weight change from the CKG baseline → display string. The backend sends a
 * POSITIVE number for a LOSS, so the sign is flipped for display: a loss shows
 * as "−5.6%", a gain as "+5.6%". */
export function fmtPenurunan(v: number | null | undefined) {
  if (v == null) return "—";
  if (v === 0) return "0%";
  return `${v > 0 ? "−" : "+"}${Math.abs(v).toFixed(1)}%`;
}

/** Colour for an interpretasi label, baseline or follow-up.
 * Order matters: "tidak tercapai" must be tested before "tercapai". */
export function interpClass(v: string) {
  const s = v.toLowerCase();
  // Follow-up legend labels (L16).
  if (s.includes("tidak tercapai")) return "bg-red-200 text-red-900";
  if (s.includes("tercapai")) return "bg-green-200 text-green-900";
  if (s.includes("missed") || s.includes("ltfu") || s.includes("loss to follow"))
    return "bg-gray-100 text-gray-700";
  // Baseline (pada tanggal berkunjung). Two bands on one scale, so Obesitas II
  // is the darker of the two rather than a different hue.
  if (s === "obesitas ii") return "bg-red-200 text-red-900";
  if (s === "obesitas i") return "bg-amber-200 text-amber-900";
  if (s === "normal") return "bg-green-200 text-green-900";
  return "";
}
