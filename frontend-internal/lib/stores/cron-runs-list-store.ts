"use client";

import { create } from "zustand";
import type { CronRunStatus } from "@/lib/api/types";

type State = {
  page: number;
  puskesmasId: string;
  status: CronRunStatus | "";
  setPage: (p: number) => void;
  setPuskesmasId: (id: string) => void;
  setStatus: (s: CronRunStatus | "") => void;
  reset: () => void;
};

export const useCronRunsListStore = create<State>((set) => ({
  page: 1,
  puskesmasId: "",
  status: "",
  setPage: (page) => set({ page }),
  setPuskesmasId: (puskesmasId) => set({ puskesmasId, page: 1 }),
  setStatus: (status) => set({ status, page: 1 }),
  reset: () => set({ page: 1, puskesmasId: "", status: "" }),
}));
