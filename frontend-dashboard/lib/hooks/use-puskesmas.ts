"use client";

import { useMemo } from "react";
import {
  keepPreviousData,
  useInfiniteQuery,
  useQuery,
} from "@tanstack/react-query";
import {
  getPuskesmas,
  listPuskesmas,
  type PuskesmasListQuery,
} from "@/lib/api/puskesmas";

export const puskesmasKeys = {
  all: ["puskesmas"] as const,
  lists: () => [...puskesmasKeys.all, "list"] as const,
  list: (q: PuskesmasListQuery) => [...puskesmasKeys.lists(), q] as const,
  infiniteLists: () => [...puskesmasKeys.all, "infiniteList"] as const,
  infiniteList: (q: { size: number; name?: string }) =>
    [...puskesmasKeys.infiniteLists(), q] as const,
  detail: (id: string) => [...puskesmasKeys.all, "detail", id] as const,
};

export function usePuskesmasList(q: PuskesmasListQuery, enabled = true) {
  return useQuery({
    queryKey: puskesmasKeys.list(q),
    queryFn: () => listPuskesmas(q),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function usePuskesmasInfiniteList(
  q: { size: number; name?: string },
  enabled = true,
) {
  return useInfiniteQuery({
    queryKey: puskesmasKeys.infiniteList(q),
    queryFn: ({ pageParam }) => listPuskesmas({ ...q, page: pageParam }),
    initialPageParam: 1,
    getNextPageParam: (last) => (last.page < last.pages ? last.page + 1 : undefined),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function usePuskesmasOptions(search: string) {
  const q = usePuskesmasInfiniteList({ size: 20, name: search.trim() || undefined });
  const options = useMemo(
    () =>
      q.data?.pages.flatMap((p) => p.items.map((i) => ({ id: i.id, label: i.name }))) ??
      [],
    [q.data],
  );
  return {
    options,
    isLoading: q.isLoading,
    isFetchingNextPage: q.isFetchingNextPage,
    hasNextPage: !!q.hasNextPage,
    fetchNextPage: q.fetchNextPage,
    error: q.error,
  };
}

export function usePuskesmas(id: string | undefined) {
  return useQuery({
    queryKey: id ? puskesmasKeys.detail(id) : ["puskesmas", "detail", "noop"],
    queryFn: () => getPuskesmas(id!),
    enabled: !!id,
  });
}
