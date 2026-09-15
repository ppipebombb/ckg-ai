import type { CapacityStats } from "@/lib/api/types";

export interface CalcInputs {
  puskesmasCount: number;
  dailyPatientsPerPuskesmas: number;
  dailyMatchesPerPuskesmas: number;
  runWindowHours: number;
  concurrency: number;
}

export interface CalcResult {
  dailyPatients: number;
  dailyMatches: number;
  /** CPU-equivalent cores to finish all daily work within runWindowHours at concurrency=1 */
  requiredCores: number;
  /** Peak RAM MB at the user's chosen concurrency level */
  peakRamMb: number;
  dailyLlmCostUsd: number;
  monthlyLlmCostUsd: number;
  scrapeLlmShareUsd: number;
  mergeLlmShareUsd: number;
  /** Concurrency-vs-cores curve for visualization */
  coresByConc: { concurrency: number; cores: number }[];
  ramByConc: { concurrency: number; ramMb: number }[];
  /** True if scrape-side stats absent — calculator falls back to merge-only sizing */
  scrapeDataMissing: boolean;
  /** True if merge-side stats absent */
  mergeDataMissing: boolean;
}

const CONC_STEPS = [1, 2, 4, 8];

const num = (v: number | null | undefined): number => v ?? 0;

export function derive(inputs: CalcInputs, stats: CapacityStats): CalcResult {
  const {
    puskesmasCount,
    dailyPatientsPerPuskesmas,
    dailyMatchesPerPuskesmas,
    runWindowHours,
    concurrency,
  } = inputs;
  const { scrape, merge } = stats;

  const dailyPatients = puskesmasCount * dailyPatientsPerPuskesmas;
  const dailyMatches = puskesmasCount * dailyMatchesPerPuskesmas;

  // CPU-second budget per day = items × sec/item × cpu_fraction
  const scrapeCpuSecPerPatient = num(scrape.avg_duration_per_patient_sec) * (num(scrape.cpu_avg_pct) / 100);
  const mergeCpuSecPerMatch = num(merge.avg_duration_per_patient_sec) * (num(merge.cpu_avg_pct) / 100);

  const dailyCpuSec = dailyPatients * scrapeCpuSecPerPatient + dailyMatches * mergeCpuSecPerMatch;
  const windowSec = Math.max(runWindowHours * 3600, 1); // guard divide-by-zero

  const requiredCores = Math.ceil(dailyCpuSec / windowSec);

  const singleSlotRamMb = Math.max(num(scrape.mem_peak_mb), num(merge.mem_peak_mb));
  const peakRamMb = singleSlotRamMb * Math.max(concurrency, 1);

  const scrapeLlmShareUsd = dailyPatients * num(scrape.avg_llm_cost_per_patient_usd);
  const mergeLlmShareUsd = dailyMatches * num(merge.avg_llm_cost_per_patient_usd);
  const dailyLlmCostUsd = scrapeLlmShareUsd + mergeLlmShareUsd;
  const monthlyLlmCostUsd = dailyLlmCostUsd * 30;

  // Total CPU work is fixed; concurrency doesn't reduce it. But you need at
  // least `c` cores to actually run `c` parallel slots — below that, slots
  // queue. Effective requirement = max(slot count, CPU-budget cores).
  const baseCores = Math.ceil(dailyCpuSec / windowSec);
  const coresByConc = CONC_STEPS.map((c) => ({
    concurrency: c,
    cores: Math.max(c, baseCores),
  }));
  const ramByConc = CONC_STEPS.map((c) => ({
    concurrency: c,
    ramMb: singleSlotRamMb * c,
  }));

  return {
    dailyPatients,
    dailyMatches,
    requiredCores,
    peakRamMb,
    dailyLlmCostUsd,
    monthlyLlmCostUsd,
    scrapeLlmShareUsd,
    mergeLlmShareUsd,
    coresByConc,
    ramByConc,
    scrapeDataMissing: scrape.sample_size === 0,
    mergeDataMissing: merge.sample_size === 0,
  };
}
