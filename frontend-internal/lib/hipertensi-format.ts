// Shared Hipertensi (blood-pressure) value formatting + pair coloring, used by
// both the monthly report table and the Full Review Diagnose table.

export function fmtBp(v: number | null | undefined) {
  if (v == null) return "—";
  return Number.isInteger(v) ? String(v) : v.toFixed(0);
}

// Pair coloring (user rule): green iff Sistole<140 AND Diastole<90 (both
// present), else red. Empty pair → no color. Applied to both the Sistolik and
// Diastolik cell of the same month.
export function bpClass(
  sys: number | null | undefined,
  dia: number | null | undefined,
) {
  if (sys == null && dia == null) return "";
  return sys != null && dia != null && sys < 140 && dia < 90
    ? "bg-green-200 text-green-900"
    : "bg-red-200 text-red-900";
}
