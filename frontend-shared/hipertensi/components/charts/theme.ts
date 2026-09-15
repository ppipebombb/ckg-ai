// Shared chart styling for the hipertensi dashboard. Colors are a small,
// accessible categorical set; status colors follow the app's green=good /
// red=bad / amber=no-show convention used elsewhere.

export const TOOLTIP_STYLE = {
  background: "var(--popover)",
  border: "1px solid var(--border)",
  borderRadius: 6,
  fontSize: 12,
} as const;

// Strokes and fills INSIDE a chart. Graphics, not text — these only need 3:1
// against the background, which they meet. Do not use them for text: see
// TEXT_COLORS.
export const COLORS = {
  registered: "#2563eb", // blue
  treated: "#0891b2", // teal
  controlled: "#16a34a", // green
  tercapai: "#16a34a", // green
  tidakTercapai: "#dc2626", // red
  tidakBerkunjung: "#d97706", // amber
  reg2025: "#2563eb",
  bothYears: "#0891b2",
  baseline2026: "#16a34a",
  currentMonth: "#7c3aed", // violet
  // Charts 7-8 "Diobati" bars: nested split (category x treated), so each
  // category keeps its Bar-3 hue and treated/untreated is the shade — solid
  // for diobati, light for tidak diobati.
  tinggiDiobati: "#dc2626", // red (== tidakTercapai)
  tinggiTidakDiobati: "#fca5a5", // light red
  terkendaliDiobati: "#16a34a", // green (== tercapai)
  terkendaliTidakDiobati: "#86efac", // light green
  baruDiobati: "#7c3aed", // violet (== currentMonth)
  baruTidakDiobati: "#c4b5fd", // light violet
  sudahDiobati: "#0891b2", // teal (== treated/bothYears)
  sudahTidakDiobati: "#a5f3fc", // light cyan
} as const;

/**
 * The same series hues, for TEXT on a card (titles, headline percentages).
 *
 * COLORS are picked to read as strokes on a chart; as 16px text they land at
 * 3.2-3.7:1 against `--card` and fail WCAG AA, which wants 4.5:1. A single hex
 * cannot pass on both a white and a near-black card, so the accessible value is
 * theme-dependent and has to come from CSS — each app defines these vars in its
 * `app/globals.css` under `:root` and `.dark` (host contract).
 */
export const TEXT_COLORS = {
  treated: "var(--chart-treated-text)",
  tercapai: "var(--chart-tercapai-text)",
  tidakTercapai: "var(--chart-tidak-tercapai-text)",
  tidakBerkunjung: "var(--chart-tidak-berkunjung-text)",
} as const;

export function pct(n: number, base: number): number {
  return base > 0 ? Math.round((n / base) * 100) : 0;
}

/**
 * Every count rendered on a chart or a chart card. Bare `toLocaleString()`
 * follows the browser's locale, so an en-US browser renders "2,396" in a point
 * label right under a card headline's id-ID "2.396" — the same number, twice,
 * differently, and "2.396" reads as two-point-four in en-US. The app is
 * Indonesian: pin the locale rather than inherit the reader's.
 */
export function fmtCount(n: number): string {
  return n.toLocaleString("id-ID");
}

/** "2026-03" → "Mar 2026" (no date-fns dependency for a bare YYYY-MM). */
const _MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
  "Jul", "Agu", "Sep", "Okt", "Nov", "Des",
];
export function fmtYm(ym: string): string {
  const [y, m] = ym.split("-");
  const idx = Number(m) - 1;
  return `${_MONTHS[idx] ?? m} ${y}`;
}
