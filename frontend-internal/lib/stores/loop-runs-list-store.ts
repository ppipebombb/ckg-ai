"use client";

import { create } from "zustand";
import type { LoopRunStatus, LoopTrigger } from "@/lib/api/types";

export type LoopStatusFilter = LoopRunStatus | "all";
export type LoopTriggerFilter = LoopTrigger | "all";

type State = {
  page: number;
  puskesmasId: string;
  status: LoopStatusFilter;
  trigger: LoopTriggerFilter;
  needsAction: boolean;
  setPage: (p: number) => void;
  setPuskesmasId: (id: string) => void;
  setStatus: (s: LoopStatusFilter) => void;
  setTrigger: (t: LoopTriggerFilter) => void;
  setNeedsAction: (v: boolean) => void;
  reset: () => void;
};

export const useLoopRunsListStore = create<State>((set) => ({
  page: 1,
  puskesmasId: "",
  status: "all",
  trigger: "all",
  needsAction: false,
  setPage: (page) => set({ page }),
  setPuskesmasId: (puskesmasId) => set({ puskesmasId, page: 1 }),
  setStatus: (status) => set({ status, page: 1 }),
  setTrigger: (trigger) => set({ trigger, page: 1 }),
  setNeedsAction: (needsAction) => set({ needsAction, page: 1 }),
  reset: () =>
    set({
      page: 1,
      puskesmasId: "",
      status: "all",
      trigger: "all",
      needsAction: false,
    }),
}));
