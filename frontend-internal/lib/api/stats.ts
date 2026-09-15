import { http } from "./client";
import { CapacityStatsOut, type CapacityStats } from "./types";

export async function getCapacityStats(windowDays: number): Promise<CapacityStats> {
  const { data } = await http.get("/admin/stats/capacity", {
    params: { window_days: windowDays },
  });
  return CapacityStatsOut.parse(data);
}
