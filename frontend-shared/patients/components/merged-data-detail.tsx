"use client";

import { useMemo } from "react";
import { format, parseISO } from "date-fns";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import {
  countSectionStats,
  countTotalStats,
  findMergedIdentity,
  parseMergedPatient,
  type MergedSection,
  type MergedSubSection,
} from "@shared/patients/merged-patient";
import { MergedDataRow } from "./merged-data-row";

export function MergedDataDetail({
  rawData,
  fallbackName,
  fallbackNik,
  filterDate,
  mergedAt,
  rightSlot,
}: {
  rawData: unknown;
  fallbackName: string;
  fallbackNik: string;
  filterDate: string;
  mergedAt: string | null;
  rightSlot?: React.ReactNode;
}) {
  const merged = useMemo(() => parseMergedPatient(rawData), [rawData]);

  if (!merged) {
    return (
      <Card className="shadow-sm">
        <CardContent className="py-8 text-center text-sm text-[var(--muted-foreground)]">
          Merged data tidak tersedia atau format tidak dikenali.
        </CardContent>
      </Card>
    );
  }

  const name =
    findMergedIdentity(merged, "Nama") || fallbackName || "(Tanpa Nama)";
  const nik = merged.nik || fallbackNik || "";
  const dob = findMergedIdentity(merged, "Tanggal lahir");
  const age = findMergedIdentity(merged, "Umur");
  const total = countTotalStats(merged);
  const mergedAtDisplay = mergedAt
    ? format(parseISO(mergedAt), "yyyy-MM-dd HH:mm")
    : null;

  return (
    <div className="space-y-5">
      <Card className="shadow-sm">
        <CardContent className="pt-5">
          <div className="flex items-start justify-between flex-wrap gap-4">
            <div>
              <div className="flex items-center gap-2 mb-1 flex-wrap">
                <h2 className="text-xl font-bold text-[var(--foreground)]">
                  {name}
                </h2>
                <span className="text-xs font-medium rounded-full px-2.5 py-0.5 bg-violet-100 text-violet-800">
                  ASIK + ePus
                </span>
              </div>
              {nik && (
                <div className="text-sm font-medium text-[var(--foreground)] mt-1">
                  NIK: {nik}
                </div>
              )}
              {dob && (
                <div className="text-sm font-medium text-[var(--foreground)]">
                  Tgl Lahir: {dob}
                </div>
              )}
              {age && (
                <div className="text-sm font-medium text-[var(--foreground)]">
                  Umur: {age}
                </div>
              )}
              <div className="mt-2 space-y-0.5">
                {filterDate && (
                  <div className="text-xs text-[var(--muted-foreground)]">
                    Scrape: {filterDate}
                  </div>
                )}
                {mergedAtDisplay && (
                  <div className="text-xs text-[var(--muted-foreground)]">
                    Merged: {mergedAtDisplay}
                  </div>
                )}
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0 flex-wrap">
              <StatPill label="Sesuai" value={total.green} tone="green" />
              <StatPill
                label="Terisi Salah Satu"
                value={total.yellow}
                tone="yellow"
              />
              <StatPill label="Berbeda" value={total.red} tone="red" />
              {rightSlot}
            </div>
          </div>
        </CardContent>
      </Card>

      {merged.sections.length === 0 && (
        <Card className="shadow-sm">
          <CardContent className="py-8 text-center text-sm text-[var(--muted-foreground)]">
            Tidak ada section pada data merged.
          </CardContent>
        </Card>
      )}

      {merged.sections.map((section) => (
        <SectionCard key={section.key} section={section} />
      ))}
    </div>
  );
}

function SectionCard({ section }: { section: MergedSection }) {
  const stats = countSectionStats(section.items);
  // Render flat layout when the section has exactly one sub-section AND that
  // sub-section is `lainnya` — same UX as before. Otherwise group into
  // sub-section cards mirroring ASIK PROD's paket UI.
  const hasMeaningfulGroups =
    section.subSections.length > 1 ||
    (section.subSections.length === 1 &&
      section.subSections[0].key !== "lainnya" &&
      section.subSections[0].key !== "identitas_pasien");

  return (
    <Card className="shadow-sm overflow-hidden p-0 gap-0">
      <CardHeader className="py-3 px-5 bg-[var(--muted)]/50 border-b border-[var(--border)]">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <h3 className="font-semibold text-[var(--foreground)] text-sm">
            {section.label}
          </h3>
          <div className="flex items-center gap-1.5 flex-wrap">
            {stats.red > 0 && (
              <Pill label={`${stats.red} berbeda`} tone="red" />
            )}
            {stats.yellow > 0 && (
              <Pill label={`${stats.yellow} Terisi Salah Satu`} tone="yellow" />
            )}
            {stats.green > 0 && (
              <Pill label={`${stats.green} sesuai`} tone="green" />
            )}
          </div>
        </div>
      </CardHeader>
      <div>
        {hasMeaningfulGroups
          ? section.subSections.map((sub) => (
              <SubSectionBlock
                key={`${section.key}-${sub.key}`}
                section={section}
                sub={sub}
              />
            ))
          : section.items.map((item, idx) => (
              <MergedDataRow
                key={`${section.key}-${idx}`}
                item={item}
                isLast={idx === section.items.length - 1}
              />
            ))}
      </div>
    </Card>
  );
}

function SubSectionBlock({
  section,
  sub,
}: {
  section: MergedSection;
  sub: MergedSubSection;
}) {
  const stats = countSectionStats(sub.items);
  const filled = sub.items.filter(
    (i) => i.merged_value !== null && i.merged_value !== "" && i.merged_value !== "-",
  ).length;
  return (
    <div className="border-b border-[var(--border)] last:border-b-0">
      <div className="py-2 px-5 bg-[var(--muted)]/20 flex items-center justify-between gap-2 flex-wrap">
        <h4 className="font-medium text-[var(--foreground)] text-xs uppercase tracking-wide">
          {sub.label}
        </h4>
        <div className="flex items-center gap-1.5 flex-wrap">
          <Pill
            label={`${filled} / ${sub.items.length} terisi`}
            tone={
              filled === sub.items.length
                ? "green"
                : filled === 0
                  ? "red"
                  : "yellow"
            }
          />
          {stats.red > 0 && <Pill label={`${stats.red} berbeda`} tone="red" />}
        </div>
      </div>
      <div>
        {sub.items.map((item, idx) => (
          <MergedDataRow
            key={`${section.key}-${sub.key}-${idx}`}
            item={item}
            isLast={idx === sub.items.length - 1}
          />
        ))}
      </div>
    </div>
  );
}

const PILL_TONE: Record<"green" | "yellow" | "red", string> = {
  green: "bg-green-100 text-green-800",
  yellow: "bg-yellow-100 text-yellow-800",
  red: "bg-red-100 text-red-800",
};

function Pill({
  label,
  tone,
}: {
  label: string;
  tone: "green" | "yellow" | "red";
}) {
  return (
    <span
      className={cn(
        "text-xs font-medium rounded px-2 py-0.5",
        PILL_TONE[tone],
      )}
    >
      {label}
    </span>
  );
}

const STAT_PILL_TONE: Record<"green" | "yellow" | "red", string> = {
  green: "bg-green-100 text-green-800",
  yellow: "bg-yellow-100 text-yellow-800",
  red: "bg-red-100 text-red-800",
};

function StatPill({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "green" | "yellow" | "red";
}) {
  return (
    <div
      className={cn(
        "min-w-[64px] rounded-md px-3 py-1.5 text-center",
        STAT_PILL_TONE[tone],
      )}
    >
      <div className="text-base font-bold leading-tight">{value}</div>
      <div className="text-[10px] uppercase tracking-wide font-medium leading-tight">
        {label}
      </div>
    </div>
  );
}
