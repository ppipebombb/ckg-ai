"use client";

import { create } from "zustand";
import type { ScrapeJobScope } from "@/lib/api/scrape";
import type { ScrapeKind } from "@/lib/api/types";

export type ScrapeKindFilter = ScrapeKind | "all";

type State = {
  page: number;
  puskesmasId: string;
  scope: ScrapeJobScope;
  kind: ScrapeKindFilter;
  setPage: (p: number) => void;
  setPuskesmasId: (id: string) => void;
  setScope: (s: ScrapeJobScope) => void;
  setKind: (k: ScrapeKindFilter) => void;
  reset: () => void;
};

export const useScrapeJobsListStore = create<State>((set) => ({
  page: 1,
  puskesmasId: "",
  scope: "all",
  kind: "all",
  setPage: (page) => set({ page }),
  setPuskesmasId: (puskesmasId) => set({ puskesmasId, page: 1 }),
  setScope: (scope) => set({ scope, page: 1 }),
  setKind: (kind) => set({ kind, page: 1 }),
  reset: () => set({ page: 1, puskesmasId: "", scope: "all", kind: "all" }),
}));
