// Tailwind classes for an ikterus band pill. "Ikterus berat" is the escalation,
// so it reads red; "Ikterus" amber; anything else muted.
export function klasifikasiClass(k: string): string {
  const s = (k || "").toLowerCase();
  if (s.includes("berat")) return "bg-rose-100 text-rose-900";
  if (s.includes("ikterus")) return "bg-amber-100 text-amber-900";
  return "text-[var(--muted-foreground)]";
}
