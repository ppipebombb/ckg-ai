// Shape produced by backend/app/prompts/merge_patient.md.

export type MergedComparisonValue = string | number | boolean | null;

export type MergedItemStatus =
  | "match"
  | "same_answer"
  | "both_empty"
  | "one_source"
  | "conflict";

export interface MergedItem {
  merged_key: string;
  merged_value: MergedComparisonValue;
  asik_question: string | null;
  epus_question: string | null;
  asik_value: MergedComparisonValue;
  epus_value: MergedComparisonValue;
  reasoning?: string | null;
  is_same_answer?: boolean;
  is_conflict: boolean;
  /** True when merged_value followed ASIK because the EPUS value was judged
   *  physically/clinically implausible (e.g. a 2 kg adult weight). */
  epus_implausible?: boolean;
  sub_section_slug?: string | null;
  sub_section_label?: string | null;
}

export interface MergedSubSection {
  key: string;
  label: string;
  items: MergedItem[];
}

export interface MergedSection {
  key: string;
  label: string;
  /** All items flattened across sub-sections — kept for legacy callers. */
  items: MergedItem[];
  /** Grouped view that mirrors ASIK PROD form's paket sub-cards. */
  subSections: MergedSubSection[];
}

export interface MergedPatient {
  nik: string | null;
  match_status?: string;
  sections: MergedSection[];
}

const SECTION_LABELS: Record<string, string> = {
  identitas_pasien: "Identitas Pasien",
  alamat_dan_domisili: "Alamat & Domisili",
  kunjungan_dan_administrasi: "Kunjungan & Administrasi",
  anamnesis: "Anamnesis",
  tanda_vital: "Tanda Vital",
  laboratorium: "Laboratorium",
  skrining: "Skrining",
  diagnosis: "Diagnosis",
  terapi_dan_tindak_lanjut: "Terapi & Tindak Lanjut",
  lainnya: "Lainnya",
};

export const STATUS_LABEL: Record<MergedItemStatus, string> = {
  match: "Sesuai",
  same_answer: "Makna Sama",
  both_empty: "Tidak Ada Data",
  one_source: "Terisi Salah Satu",
  conflict: "Konflik Data",
};

function humanize(slug: string): string {
  return slug
    .split("_")
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

const _SLUG_RE = /^[a-z0-9]+(?:_[a-z0-9]+)+$/;

function humanizeSegment(segment: string): string {
  const trimmed = segment.trim();
  if (!trimmed) return trimmed;
  return _SLUG_RE.test(trimmed) ? humanize(trimmed) : trimmed;
}

function humanizeBreadcrumb(value: string | null): string | null {
  if (!value) return value;
  return value
    .split(">")
    .map((segment) => humanizeSegment(segment))
    .join(" > ");
}

export function isEmptyValue(v: MergedComparisonValue): boolean {
  return v === null || v === undefined || v === "" || v === "-";
}

export function getItemStatus(item: MergedItem): MergedItemStatus {
  const ae = isEmptyValue(item.asik_value);
  const ee = isEmptyValue(item.epus_value);
  if (ae && ee) return "both_empty";
  if (ae || ee) return "one_source";
  if (item.is_conflict) return "conflict";
  if (item.is_same_answer) return "same_answer";
  return "match";
}

export interface MergedStats {
  green: number;
  yellow: number;
  red: number;
  gray: number;
}

export function countSectionStats(items: MergedItem[]): MergedStats {
  let green = 0,
    yellow = 0,
    red = 0,
    gray = 0;
  for (const item of items) {
    const s = getItemStatus(item);
    if (s === "match" || s === "same_answer") green++;
    else if (s === "one_source") yellow++;
    else if (s === "both_empty") gray++;
    else red++;
  }
  return { green, yellow, red, gray };
}

export function countTotalStats(p: MergedPatient): MergedStats {
  return p.sections.reduce<MergedStats>(
    (acc, s) => {
      const c = countSectionStats(s.items);
      return {
        green: acc.green + c.green,
        yellow: acc.yellow + c.yellow,
        red: acc.red + c.red,
        gray: acc.gray + c.gray,
      };
    },
    { green: 0, yellow: 0, red: 0, gray: 0 },
  );
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function asMergedValue(v: unknown): MergedComparisonValue {
  if (v === null || v === undefined) return null;
  if (typeof v === "boolean") return v;
  if (typeof v === "string") return v;
  if (typeof v === "number") return v;
  return JSON.stringify(v);
}

function asMergedItem(v: unknown): MergedItem | null {
  if (!isRecord(v)) return null;
  if (typeof v.merged_key !== "string") return null;
  return {
    merged_key: v.merged_key,
    merged_value: asMergedValue(v.merged_value),
    asik_question: humanizeBreadcrumb(
      typeof v.asik_question === "string" ? v.asik_question : null,
    ),
    epus_question: humanizeBreadcrumb(
      typeof v.epus_question === "string" ? v.epus_question : null,
    ),
    asik_value: asMergedValue(v.asik_value),
    epus_value: asMergedValue(v.epus_value),
    reasoning: typeof v.reasoning === "string" ? v.reasoning : null,
    is_same_answer: v.is_same_answer === true,
    is_conflict: v.is_conflict === true,
    epus_implausible: v.epus_implausible === true,
    sub_section_slug:
      typeof v.sub_section_slug === "string" ? v.sub_section_slug : null,
    sub_section_label:
      typeof v.sub_section_label === "string" ? v.sub_section_label : null,
  };
}

function buildSubSections(items: MergedItem[]): MergedSubSection[] {
  // Group items by sub_section_slug while preserving first-seen order.
  const order: string[] = [];
  const map = new Map<string, MergedSubSection>();
  for (const it of items) {
    const slug = it.sub_section_slug || "lainnya";
    const label = it.sub_section_label || "Lainnya";
    if (!map.has(slug)) {
      order.push(slug);
      map.set(slug, { key: slug, label, items: [] });
    }
    map.get(slug)!.items.push(it);
  }
  return order.map((slug) => map.get(slug)!);
}

export function parseMergedPatient(raw: unknown): MergedPatient | null {
  if (!isRecord(raw)) return null;
  const sectionsRecord = isRecord(raw.sections) ? raw.sections : null;
  if (!sectionsRecord) return null;
  const sections: MergedSection[] = [];
  for (const [key, value] of Object.entries(sectionsRecord)) {
    let items: MergedItem[] = [];
    let subSections: MergedSubSection[] = [];
    let label = SECTION_LABELS[key] ?? humanize(key);

    if (Array.isArray(value)) {
      // Legacy flat shape — group on the fly using item sub_section hints,
      // falling back to a single `Lainnya` sub-section.
      items = value
        .map(asMergedItem)
        .filter((i): i is MergedItem => i !== null);
      if (items.length === 0) continue;
      subSections = buildSubSections(items);
    } else if (isRecord(value)) {
      // Nested shape: {layanan_label, sub_sections: {slug: {label, items}}}.
      const layananLabel =
        typeof value.layanan_label === "string" ? value.layanan_label : null;
      if (layananLabel) label = layananLabel;
      const subRecord = isRecord(value.sub_sections) ? value.sub_sections : null;
      if (!subRecord) continue;
      for (const [subKey, subVal] of Object.entries(subRecord)) {
        if (!isRecord(subVal)) continue;
        const subLabel =
          typeof subVal.label === "string" ? subVal.label : humanize(subKey);
        const subItems = Array.isArray(subVal.items) ? subVal.items : [];
        const parsedItems = subItems
          .map(asMergedItem)
          .filter((i): i is MergedItem => i !== null);
        if (parsedItems.length === 0) continue;
        subSections.push({ key: subKey, label: subLabel, items: parsedItems });
        items.push(...parsedItems);
      }
      if (items.length === 0) continue;
    } else {
      continue;
    }

    sections.push({ key, label, items, subSections });
  }
  // Identitas Pasien is the most informational section — always render it first
  // on the detail page, regardless of where it sits in the backend payload.
  const idIdx = sections.findIndex((s) => s.key === "identitas_pasien");
  if (idIdx > 0) sections.unshift(sections.splice(idIdx, 1)[0]);
  return {
    nik: typeof raw.nik === "string" ? raw.nik : null,
    match_status: typeof raw.match_status === "string" ? raw.match_status : undefined,
    sections,
  };
}

export function findMergedIdentity(
  p: MergedPatient,
  mergedKey: string,
): string | null {
  const id = p.sections.find((s) => s.key === "identitas_pasien");
  if (!id) return null;
  const found = id.items.find(
    (i) => i.merged_key.toLowerCase() === mergedKey.toLowerCase(),
  );
  if (!found) return null;
  const v = found.merged_value;
  if (v === null || v === undefined || v === "") return null;
  return String(v);
}

export function formatMergedValue(v: MergedComparisonValue): string | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "boolean") return v ? "Ya" : "Tidak";
  if (typeof v === "number") return String(v);
  const s = v.trim();
  if (!s || s === "-") return null;
  return s;
}

export function formatRawValue(v: MergedComparisonValue): string {
  if (v === null || v === undefined) return "— (null)";
  if (v === "") return "— (kosong)";
  if (v === "-") return "— (placeholder)";
  if (typeof v === "boolean") return v ? "Ya" : "Tidak";
  return String(v);
}
