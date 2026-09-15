"use client";

import { useQuery } from "@tanstack/react-query";
import { getCapacityStats } from "@/lib/api/stats";
import type { CapacityStats } from "@/lib/api/types";

export const statsKeys = {
  all: ["stats"] as const,
  capacity: (windowDays: number) => ["stats", "capacity", windowDays] as const,
};

export function useCapacityStats(windowDays: number = 30) {
  return useQuery<CapacityStats>({
    queryKey: statsKeys.capacity(windowDays),
    queryFn: () => getCapacityStats(windowDays),
    staleTime: 5 * 60_000,
  });
}
