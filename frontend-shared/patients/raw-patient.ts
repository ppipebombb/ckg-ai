export type RawSource = "asik" | "epus";

export type ComparisonValue = string | null | boolean;

export interface PatientItem {
  merged_key: string;
  merged_value: ComparisonValue;
  question: string;
}

export interface PatientGroup {
  key: string;
  label: string;
  items: PatientItem[];
}

export interface PatientSection {
  key: string;
  label: string;
  items: PatientItem[];
  groups: PatientGroup[];
}

export interface PatientTable {
  key: string;
  tabLabel: string;
  tableLabel: string;
  headers: string[];
  rows: Record<string, string | null>[];
}

export interface BuiltPatient {
  nik: string | null;
  source: RawSource;
  sections: PatientSection[];
  tables: PatientTable[];
}

type JsonRecord = Record<string, unknown>;

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asRecord(value: unknown): JsonRecord {
  return isRecord(value) ? value : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function cleanLabel(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function slugify(value: string): string {
  const slug = cleanLabel(value)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return slug || "section";
}

function toComparisonValue(value: unknown): ComparisonValue {
  if (value === null || value === undefined) return null;
  if (typeof value === "boolean") return value;
  if (typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  return JSON.stringify(value);
}

function walkLeaves(
  value: unknown,
  path: string[] = [],
): Array<{ path: string[]; value: unknown }> {
  if (isRecord(value)) {
    return Object.entries(value).flatMap(([key, child]) =>
      walkLeaves(child, [...path, key]),
    );
  }
  if (Array.isArray(value)) {
    return value.flatMap((child, index) =>
      walkLeaves(child, [...path, String(index + 1)]),
    );
  }
  return path.length > 0 ? [{ path, value }] : [];
}

function getNested(record: JsonRecord, keys: string[]): unknown {
  let cursor: unknown = record;
  for (const key of keys) {
    if (!isRecord(cursor)) return undefined;
    cursor = cursor[key];
  }
  return cursor;
}

function getNik(source: RawSource, raw: unknown, fallbackNik: string): string | null {
  const record = asRecord(raw);
  const value =
    source === "asik"
      ? getNested(record, ["detail_data", "data_individu", "NIK"])
      : getNested(record, ["data_pasien", "NIK"]);
  return typeof value === "string" && value.trim() ? value : fallbackNik || null;
}

function identityMergedKey(source: RawSource, key: string): string {
  if (source === "epus") {
    const epusMap: Record<string, string> = {
      NIK: "NIK",
      "Nama Pasien": "Nama",
      "Nama Ibu": "Nama ibu/wali",
      "Jenis Kelamin": "Jenis kelamin",
      Umur: "Umur",
      "Tempat/Tgl Lahir": "Tanggal lahir",
    };
    return epusMap[key] ?? key;
  }
  const asikMap: Record<string, string> = {
    "Tanggal Lahir": "Tanggal lahir",
    "Jenis Kelamin": "Jenis kelamin",
    "Nama Ibu/Wali": "Nama ibu/wali",
  };
  return asikMap[key] ?? key;
}

function makeItem(
  mergedKey: string,
  question: string,
  value: unknown,
): PatientItem {
  return {
    merged_key: mergedKey,
    merged_value: toComparisonValue(value),
    question,
  };
}

function flattenRecordSection(
  source: RawSource,
  record: unknown,
  questionPrefix: string,
  mergedKeyForPath: (path: string[]) => string = (path) =>
    path.at(-1) ?? "Field",
): PatientItem[] {
  return walkLeaves(record).map(({ path, value }) => {
    const cleanPath = path.map(cleanLabel);
    return makeItem(
      cleanLabel(mergedKeyForPath(cleanPath)),
      [questionPrefix, ...cleanPath].join(" > "),
      value,
    );
  });
}

function appendSection(
  sections: PatientSection[],
  key: string,
  label: string,
  items: PatientItem[],
) {
  if (items.length === 0) return;
  const existing = sections.find((s) => s.key === key);
  if (existing) {
    existing.items.push(...items);
  } else {
    sections.push({ key, label, items, groups: [] });
  }
}

function appendSectionWithGroups(
  sections: PatientSection[],
  key: string,
  label: string,
  groups: PatientGroup[],
) {
  const nonEmpty = groups.filter((g) => g.items.length > 0);
  if (nonEmpty.length === 0) return;
  sections.push({ key, label, items: [], groups: nonEmpty });
}

const EPUS_NOISE_GROUPS = new Set(["Pasien Pulang"]);

function buildAsik(raw: unknown, fallbackNik: string): BuiltPatient {
  const record = asRecord(raw);
  const detail = asRecord(record.detail_data);
  const sections: PatientSection[] = [];

  appendSection(
    sections,
    "identitas_pasien",
    "Identitas Pasien",
    flattenRecordSection("asik", detail.data_individu, "Data Individu", (path) =>
      identityMergedKey("asik", path.at(-1) ?? "Field"),
    ),
  );
  appendSection(
    sections,
    "alamat_dan_domisili",
    "Alamat & Domisili",
    flattenRecordSection("asik", detail.data_domisili, "Data Domisili"),
  );

  for (const [arrayKey, sectionKey, sectionLabel] of [
    ["pemeriksaan_mandiri", "asik_pemeriksaan_mandiri", "Pemeriksaan Mandiri"],
    ["pelayanan_nakes", "asik_pelayanan_nakes", "Pelayanan Nakes"],
  ] as const) {
    const items = asArray(record[arrayKey]).flatMap((entry) => {
      const entryRecord = asRecord(entry);
      const layanan =
        typeof entryRecord.layanan === "string" && entryRecord.layanan.trim()
          ? entryRecord.layanan
          : sectionLabel;
      return flattenRecordSection("asik", entryRecord.form_data, layanan);
    });
    appendSection(sections, sectionKey, sectionLabel, items);
  }

  return {
    nik: getNik("asik", raw, fallbackNik),
    source: "asik",
    sections,
    tables: [],
  };
}

// Formulir Skrining (CKG screening battery) — `skrining_klaster` answers are
// stored keyed by raw form field name (the scraper kept the answers but not the
// question text). This map restores the real question per screening so the raw
// view reads like the form. Unmapped screenings/fields fall back to a humanized
// field name (humanizeFieldName). Screening keys match the scraper's getlist
// `key` (e.g. "hipertensi"); add a block here as other screenings are verified.
const SKRINING_QUESTION_LABELS: Record<string, Record<string, string>> = {
  hipertensi: {
    riwayat_pribadi: "Apakah pasien pernah dinyatakan tekanan darah tinggi?",
    riwayat_keluarga: "Riwayat keluarga Tekanan Darah Tinggi (Hipertensi)",
    riwayat_merokok: "Riwayat Merokok",
    riwayat_alkohol: "Riwayat Minum alkohol / Merokok di Keluarga",
    makan_asin: "Kebiasaan makan asin",
    aktifitas_fisik: "Aktifitas fisik setiap hari",
    istirahat_cukup: "Istirahat cukup",
    kurang_buah_sayur: "Kurang Makan Buah dan Sayur",
    sistole: "Sistole",
    diastole: "Diastole",
    klasifikasi_ht: "Klasifikasi Hipertensi",
    tanggal: "Tanggal Skrining",
    petugas_nama: "Nama Petugas",
  },
};

// Database/UI scaffolding fields on a screening record/detail that are not
// patient answers — dropped from the rendered Skrining section.
const SKRINING_NOISE_FIELDS = new Set<string>([
  "id",
  "skrining_id",
  "header_id",
  "petugas_id",
  "dokter_id",
  "pelayanan_id",
  "pasien_id",
  "created_at",
  "updated_at",
  "warna_badge",
  "nama",
]);

function humanizeFieldName(name: string): string {
  return (
    cleanLabel(name.replace(/[_-]+/g, " ")).replace(/\b\w/g, (c) =>
      c.toUpperCase(),
    ) || name
  );
}

// Fallback label for any skrining field with no entry in SKRINING_QUESTION_LABELS.
// Vue-form screenings (PHQ-4, …) store answers under `q::<normalized question>`
// keys whose suffix already IS the question text — surface it as a sentence
// rather than title-casing every word. Everything else is a snake_case field
// name → humanize it.
function skriningFieldLabel(field: string): string {
  if (field.startsWith("q::")) {
    const q = cleanLabel(field.slice(3));
    return q ? q.charAt(0).toUpperCase() + q.slice(1) : field;
  }
  return humanizeFieldName(field);
}

function buildEpus(raw: unknown, fallbackNik: string): BuiltPatient {
  const record = asRecord(raw);
  const sections: PatientSection[] = [];
  const tables: PatientTable[] = [];

  appendSection(
    sections,
    "identitas_pasien",
    "Identitas Pasien",
    flattenRecordSection("epus", record.data_pasien, "Data Pasien", (path) =>
      identityMergedKey("epus", path.at(-1) ?? "Field"),
    ),
  );

  // CKG (Cek Kesehatan Gratis) — placed right after Identitas Pasien for
  // quick visibility. Always shows a status row so "Belum CKG" is visible
  // too, plus one row per recorded CKG date.
  const ckg = asRecord(record.ckg);
  const ckgItems: PatientItem[] = [
    makeItem(
      "Tandai CKG",
      "CKG > Tandai",
      ckg.sudah_ckg === true ? "Ya" : "Tidak",
    ),
  ];
  for (const entry of asArray(ckg.tanggal)) {
    const t = asRecord(entry);
    const display =
      typeof t.display === "string" && t.display.trim()
        ? t.display
        : typeof t.iso === "string" && t.iso.trim()
          ? t.iso
          : null;
    if (display) ckgItems.push(makeItem("Tanggal CKG", "CKG > Tanggal", display));
  }
  appendSection(sections, "epus_ckg", "CKG (Cek Kesehatan Gratis)", ckgItems);

  appendSection(
    sections,
    "epus_penyakit_khusus",
    "Penyakit Khusus",
    flattenRecordSection(
      "epus",
      record.penyakit_khusus,
      "Penyakit Khusus",
      (path) => path.join(" > "),
    ),
  );
  appendSection(
    sections,
    "epus_risiko_kehamilan",
    "Risiko Kehamilan",
    flattenRecordSection(
      "epus",
      record.risiko_kehamilan,
      "Risiko Kehamilan",
      (path) => path.join(" > "),
    ),
  );

  // Formulir Skrining (CKG screening battery: Hipertensi / DM / PHQ-4 / PUMA /
  // SKILAS / ADL / …). One group per completed screening; answers come from the
  // record + edit-page detail (detail wins, mirroring the backend converter's
  // _skrining_index), labeled with the real form question where known.
  const skriningKlaster = asRecord(record.skrining_klaster);
  const skriningGroups: PatientGroup[] = [];
  for (const [screeningKey, screeningValue] of Object.entries(skriningKlaster)) {
    const screening = asRecord(screeningValue);
    const record0 = asRecord(asArray(screening.records)[0]);
    const detail = asRecord(screening.detail);
    const flat: JsonRecord = { ...record0, ...detail };
    const labelMap = SKRINING_QUESTION_LABELS[screeningKey] ?? {};
    const groupLabel =
      typeof screening.nama === "string" && screening.nama.trim()
        ? cleanLabel(screening.nama)
        : humanizeFieldName(screeningKey);
    const items: PatientItem[] = [];
    for (const [field, value] of Object.entries(flat)) {
      if (SKRINING_NOISE_FIELDS.has(field)) continue;
      const question = labelMap[field] ?? skriningFieldLabel(field);
      items.push(
        makeItem(question, `Formulir Skrining > ${groupLabel} > ${question}`, value),
      );
    }
    if (items.length === 0) continue;
    skriningGroups.push({
      key: `epus_skrining__${slugify(screeningKey)}`,
      label: groupLabel,
      items,
    });
  }
  appendSectionWithGroups(
    sections,
    "epus_skrining_klaster",
    "Formulir Skrining",
    skriningGroups,
  );

  const tabs = asRecord(record.tabs);
  for (const [tabName, tabValue] of Object.entries(tabs)) {
    const tabRecord = asRecord(tabValue);
    const sectionKey = `epus_tab_${slugify(tabName)}`;
    const fieldsRecord = isRecord(tabRecord.fields) ? tabRecord.fields : null;

    if (fieldsRecord) {
      const groups: PatientGroup[] = [];
      for (const [groupName, groupValue] of Object.entries(fieldsRecord)) {
        if (EPUS_NOISE_GROUPS.has(groupName.trim())) continue;
        const items = isRecord(groupValue)
          ? flattenRecordSection("epus", groupValue, `${tabName} > ${groupName}`)
          : flattenRecordSection("epus", { [groupName]: groupValue }, tabName);
        if (items.length === 0) continue;
        groups.push({
          key: `${sectionKey}__${slugify(groupName)}`,
          label: cleanLabel(groupName),
          items,
        });
      }
      appendSectionWithGroups(sections, sectionKey, tabName, groups);
    } else {
      appendSection(
        sections,
        sectionKey,
        tabName,
        flattenRecordSection("epus", tabRecord, tabName),
      );
    }

    const tablesRecord = isRecord(tabRecord.tables) ? tabRecord.tables : null;
    if (tablesRecord) {
      for (const [tableName, rowsValue] of Object.entries(tablesRecord)) {
        if (!Array.isArray(rowsValue)) continue;
        const recordRows = rowsValue.filter(isRecord);
        if (recordRows.length === 0) continue;
        const headerSet: string[] = [];
        const seen = new Set<string>();
        for (const r of recordRows) {
          for (const k of Object.keys(r)) {
            if (!seen.has(k)) {
              seen.add(k);
              headerSet.push(k);
            }
          }
        }
        const rows = recordRows.map((r) => {
          const out: Record<string, string | null> = {};
          for (const h of headerSet) {
            const v = toComparisonValue(r[h]);
            out[h] = typeof v === "boolean" ? String(v) : v;
          }
          return out;
        });
        const hasAnyValue = rows.some((r) =>
          headerSet.some((h) => r[h] !== null && r[h] !== ""),
        );
        if (!hasAnyValue) continue;
        tables.push({
          key: `${sectionKey}__table_${slugify(tableName)}`,
          tabLabel: tabName,
          tableLabel: cleanLabel(tableName),
          headers: headerSet,
          rows,
        });
      }
    }
  }

  return {
    nik: getNik("epus", raw, fallbackNik),
    source: "epus",
    sections,
    tables,
  };
}

export function buildPatientFromRawSource(
  source: RawSource,
  raw: unknown,
  fallbackNik: string,
): BuiltPatient {
  return source === "asik" ? buildAsik(raw, fallbackNik) : buildEpus(raw, fallbackNik);
}

export function findIdentity(
  built: BuiltPatient,
  mergedKey: string,
): string | null {
  const id = built.sections.find((s) => s.key === "identitas_pasien");
  if (!id) return null;
  const it = id.items.find(
    (i) => i.merged_key.toLowerCase() === mergedKey.toLowerCase(),
  );
  if (!it) return null;
  const v = it.merged_value;
  if (v === null || v === undefined || v === false) return null;
  const s = String(v);
  return s.trim() ? s : null;
}
