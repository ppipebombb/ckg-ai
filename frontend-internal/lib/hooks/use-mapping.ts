import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { mappingApi } from "@/lib/api/mapping";

export const mappingKeys = {
  all: ["mapping"] as const,
  overview: () => [...mappingKeys.all, "overview"] as const,
  lists: () => [...mappingKeys.all, "list"] as const,
  list: (params: {
    q?: string;
    coverage?: string;
    has_audit?: boolean;
    page: number;
    size: number;
  }) => [...mappingKeys.lists(), params] as const,
  details: () => [...mappingKeys.all, "detail"] as const,
  detail: (frm: string) => [...mappingKeys.details(), frm] as const,
  epusPaths: (q?: string) => [...mappingKeys.all, "epus-paths", q ?? ""] as const,
};

export function useMappingOverview() {
  return useQuery({
    queryKey: mappingKeys.overview(),
    queryFn: () => mappingApi.overview(),
    staleTime: 5 * 60 * 1000,
  });
}

export function useMappingForms(params: {
  q?: string;
  coverage?: "covered" | "partial" | "none";
  has_audit?: boolean;
  page: number;
  size: number;
}) {
  return useQuery({
    queryKey: mappingKeys.list(params),
    queryFn: () => mappingApi.listForms(params),
    placeholderData: keepPreviousData,
    staleTime: 60 * 1000,
  });
}

export function useMappingForm(frm: string | null) {
  return useQuery({
    queryKey: mappingKeys.detail(frm ?? ""),
    queryFn: () => mappingApi.getForm(frm!),
    enabled: !!frm,
    staleTime: 5 * 60 * 1000,
  });
}

export function useEpusPaths(q?: string) {
  return useQuery({
    queryKey: mappingKeys.epusPaths(q),
    queryFn: () => mappingApi.listEpusPaths(q),
    staleTime: 60 * 1000,
  });
}
