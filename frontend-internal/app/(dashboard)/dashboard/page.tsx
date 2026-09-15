"use client";

import { useState } from "react";
import { StatCard } from "@/components/common/stat-card";
import { useAdminMe } from "@/lib/hooks/use-auth";
import { usePuskesmasList } from "@/lib/hooks/use-puskesmas";
import { useUsersList } from "@/lib/hooks/use-users";
import { useLlmConfigsList } from "@/lib/hooks/use-llm";
import { useCapacityStats } from "@/lib/hooks/use-stats";
import { HipertensiChartsSection } from "@/components/dashboard/hipertensi-charts-section";

const ONE = { page: 1, size: 1 };
const WINDOWS = [7, 30, 90] as const;

function fmt(n: number | null | undefined, decimals = 0): string {
  if (n == null) return "—";
  return n.toFixed(decimals);
}

export default function DashboardPage() {
  const me = useAdminMe(true);
  const puskesmas = usePuskesmasList(ONE);
  const users = useUsersList(ONE);
  const configs = useLlmConfigsList(ONE);
  const [windowDays, setWindowDays] = useState<7 | 30 | 90>(30);
  const stats = useCapacityStats(windowDays);

  const scrape = stats.data?.scrape;
  const merge = stats.data?.merge;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Dashboard</h1>
        <p className="text-sm text-[var(--muted-foreground)]">
          Selamat datang kembali{me.data ? `, ${me.data.full_name}` : ""}.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <StatCard
          title="Puskesmas"
          value={puskesmas.isLoading ? undefined : puskesmas.data?.total ?? 0}
          loading={puskesmas.isLoading}
        />
        <StatCard
          title="Pengguna"
          value={users.isLoading ? undefined : users.data?.total ?? 0}
          loading={users.isLoading}
        />
        <StatCard
          title="Konfigurasi LLM"
          value={configs.isLoading ? undefined : configs.data?.total ?? 0}
          loading={configs.isLoading}
        />
      </div>

      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-[var(--muted-foreground)]">
          Rata-rata Sumber Daya
        </h2>
        <div className="flex gap-1">
          {WINDOWS.map((w) => (
            <button
              key={w}
              onClick={() => setWindowDays(w)}
              className={`rounded px-2 py-0.5 text-xs transition-colors ${
                windowDays === w
                  ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                  : "text-[var(--muted-foreground)] hover:bg-[var(--accent)]"
              }`}
            >
              {w}d
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-2">
        <h3 className="text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]/80">
          Job Scrape
        </h3>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <StatCard
            title="Rata-rata CPU per scrape"
            value={scrape?.cpu_avg_pct != null ? `${fmt(scrape.cpu_avg_pct, 1)}%` : undefined}
            subtext={
              scrape?.cpu_peak_pct != null
                ? `puncak ${fmt(scrape.cpu_peak_pct, 1)}% • ${scrape.sample_size} job`
                : undefined
            }
            loading={stats.isLoading}
          />
          <StatCard
            title="Rata-rata RAM per scrape"
            value={scrape?.mem_avg_mb != null ? `${fmt(scrape.mem_avg_mb, 0)} MB` : undefined}
            subtext={
              scrape?.mem_peak_mb != null
                ? `puncak ${fmt(scrape.mem_peak_mb, 0)} MB`
                : undefined
            }
            loading={stats.isLoading}
          />
          <StatCard
            title="Rata-rata durasi per pasien"
            value={
              scrape?.avg_duration_per_patient_sec != null
                ? `${fmt(scrape.avg_duration_per_patient_sec, 2)}s`
                : undefined
            }
            subtext={
              scrape?.total_patients != null
                ? `${scrape.total_patients.toLocaleString()} pasien`
                : undefined
            }
            loading={stats.isLoading}
          />
        </div>
      </div>

      <div className="space-y-2">
        <h3 className="text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]/80">
          Job Merge
        </h3>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <StatCard
            title="Rata-rata CPU & RAM per merge"
            value={
              merge?.cpu_avg_pct != null && merge?.mem_avg_mb != null
                ? `${fmt(merge.cpu_avg_pct, 1)}% · ${fmt(merge.mem_avg_mb, 0)} MB`
                : undefined
            }
            subtext={
              merge?.cpu_peak_pct != null && merge?.mem_peak_mb != null
                ? `puncak ${fmt(merge.cpu_peak_pct, 1)}% · ${fmt(merge.mem_peak_mb, 0)} MB • ${merge.sample_size} job`
                : undefined
            }
            loading={stats.isLoading}
          />
          <StatCard
            title="Biaya LLM per kecocokan"
            value={
              merge?.avg_llm_cost_per_patient_usd != null
                ? `$${merge.avg_llm_cost_per_patient_usd.toFixed(6)}`
                : undefined
            }
            subtext={
              merge?.total_llm_cost_usd != null
                ? `total $${merge.total_llm_cost_usd.toFixed(4)}`
                : undefined
            }
            loading={stats.isLoading}
          />
          <StatCard
            title="Rata-rata durasi per pasien"
            value={
              merge?.avg_duration_per_patient_sec != null
                ? `${fmt(merge.avg_duration_per_patient_sec, 2)}s`
                : undefined
            }
            subtext={
              merge?.total_patients != null
                ? `${merge.total_patients.toLocaleString()} pasien`
                : undefined
            }
            loading={stats.isLoading}
          />
        </div>
      </div>

      <HipertensiChartsSection />
    </div>
  );
}
