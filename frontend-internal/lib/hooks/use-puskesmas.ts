"use client";

import { useMemo } from "react";
import {
  InfiniteData,
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  clearCredentials,
  createPuskesmas,
  decryptCredentials,
  deletePuskesmas,
  getPuskesmas,
  listPuskesmas,
  setCredentials,
  updatePuskesmas,
  type CredKind,
  type PuskesmasListQuery,
} from "@/lib/api/puskesmas";
import type {
  CredInput,
  Page,
  Puskesmas,
  PuskesmasDetail,
  PuskesmasCreateInput,
  PuskesmasUpdateInput,
} from "@/lib/api/types";

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

export function useCreatePuskesmas() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: PuskesmasCreateInput) => createPuskesmas(input),
    onSuccess: (created) => {
      qc.setQueriesData<Page<Puskesmas>>(
        { queryKey: puskesmasKeys.lists() },
        (old) =>
          old
            ? { ...old, items: [created, ...old.items], total: old.total + 1 }
            : old,
      );
      qc.setQueriesData<InfiniteData<Page<Puskesmas>>>(
        { queryKey: puskesmasKeys.infiniteLists() },
        (old) =>
          old
            ? {
                ...old,
                pages: old.pages.map((pg, i) =>
                  i === 0
                    ? { ...pg, items: [created, ...pg.items], total: pg.total + 1 }
                    : { ...pg, total: pg.total + 1 },
                ),
              }
            : old,
      );
    },
  });
}

export function useUpdatePuskesmas() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: PuskesmasUpdateInput }) =>
      updatePuskesmas(id, input),
    onSuccess: (updated: PuskesmasDetail) => {
      qc.setQueryData(puskesmasKeys.detail(updated.id), updated);
      qc.setQueriesData<Page<Puskesmas>>(
        { queryKey: puskesmasKeys.lists() },
        (old) =>
          old
            ? {
                ...old,
                items: old.items.map((p) => (p.id === updated.id ? updated : p)),
              }
            : old,
      );
      qc.setQueriesData<InfiniteData<Page<Puskesmas>>>(
        { queryKey: puskesmasKeys.infiniteLists() },
        (old) =>
          old
            ? {
                ...old,
                pages: old.pages.map((pg) => ({
                  ...pg,
                  items: pg.items.map((p) => (p.id === updated.id ? updated : p)),
                })),
              }
            : old,
      );
    },
  });
}

export function useDeletePuskesmas() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deletePuskesmas(id),
    onSuccess: (_void, id) => {
      qc.removeQueries({ queryKey: puskesmasKeys.detail(id) });
      qc.setQueriesData<Page<Puskesmas>>(
        { queryKey: puskesmasKeys.lists() },
        (old) =>
          old
            ? {
                ...old,
                items: old.items.filter((p) => p.id !== id),
                total: Math.max(0, old.total - 1),
              }
            : old,
      );
      qc.setQueriesData<InfiniteData<Page<Puskesmas>>>(
        { queryKey: puskesmasKeys.infiniteLists() },
        (old) =>
          old
            ? {
                ...old,
                pages: old.pages.map((pg) => ({
                  ...pg,
                  items: pg.items.filter((p) => p.id !== id),
                  total: Math.max(0, pg.total - 1),
                })),
              }
            : old,
      );
    },
  });
}

export function useSetCredentials() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      kind,
      input,
    }: {
      id: string;
      kind: CredKind;
      input: CredInput;
    }) => setCredentials(id, kind, input),
    onSuccess: (_void, { id }) => {
      // Server-derived field: invalidate to refresh is_*_cred_set
      qc.invalidateQueries({ queryKey: puskesmasKeys.detail(id) });
    },
  });
}

export function useClearCredentials() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, kind }: { id: string; kind: CredKind }) =>
      clearCredentials(id, kind),
    onSuccess: (_void, { id }) => {
      // Server-derived field: invalidate to refresh is_*_cred_set
      qc.invalidateQueries({ queryKey: puskesmasKeys.detail(id) });
    },
  });
}

export function useDecryptCredentials() {
  return useMutation({
    mutationFn: ({ id, kind }: { id: string; kind: CredKind }) =>
      decryptCredentials(id, kind),
  });
}
