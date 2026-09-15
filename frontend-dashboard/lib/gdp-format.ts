// Shared GDP value formatting + coloring, used by both the monthly report
// table and the Full Review Diagnose table.

export const MONTHS_ID = [
  "Januari",
  "Februari",
  "Maret",
  "April",
  "Mei",
  "Juni",
  "Juli",
  "Agustus",
  "September",
  "Oktober",
  "November",
  "Desember",
];

export function fmtGdp(v: number | null | undefined) {
  if (v == null) return "—";
  return Number.isInteger(v) ? String(v) : v.toFixed(0);
}

// Mirrors spreadsheet conditional formatting on G3:R33766:
//   80 ≤ v ≤ 130 → green (Terkendali range)
//   else         → red
export function gdpClass(v: number | null | undefined) {
  if (v == null) return "";
  return v >= 80 && v <= 130
    ? "bg-green-200 text-green-900"
    : "bg-red-200 text-red-900";
}
