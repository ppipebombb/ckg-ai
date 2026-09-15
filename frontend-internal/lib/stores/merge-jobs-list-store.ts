"use client";

import { create } from "zustand";
import type { MergeJobScope } from "@/lib/api/merge";
import type { MergeStatus } from "@/lib/api/types";

type State = {
  page: number;
  puskesmasId: string;
  dateFilter: string;
  status: MergeStatus | "";
  scope: MergeJobScope;
  setPage: (p: number) => void;
  setPuskesmasId: (id: string) => void;
  setDateFilter: (d: string) => void;
  setStatus: (s: MergeStatus | "") => void;
  setScope: (s: MergeJobScope) => void;
  reset: () => void;
};

export const useMergeJobsListStore = create<State>((set) => ({
  page: 1,
  puskesmasId: "",
  dateFilter: "",
  status: "",
  scope: "all",
  setPage: (page) => set({ page }),
  setPuskesmasId: (puskesmasId) => set({ puskesmasId, page: 1 }),
  setDateFilter: (dateFilter) => set({ dateFilter, page: 1 }),
  setStatus: (status) => set({ status, page: 1 }),
  setScope: (scope) => set({ scope, page: 1 }),
  reset: () =>
    set({ page: 1, puskesmasId: "", dateFilter: "", status: "", scope: "all" }),
}));
