"use client";

import { create } from "zustand";
import type { SyncStatus } from "@/lib/api/types";

type State = {
  page: number;
  puskesmasId: string;
  status: SyncStatus | "";
  setPage: (p: number) => void;
  setPuskesmasId: (id: string) => void;
  setStatus: (s: SyncStatus | "") => void;
  reset: () => void;
};

export const useSyncJobsListStore = create<State>((set) => ({
  page: 1,
  puskesmasId: "",
  status: "",
  setPage: (page) => set({ page }),
  setPuskesmasId: (puskesmasId) => set({ puskesmasId, page: 1 }),
  setStatus: (status) => set({ status, page: 1 }),
  reset: () => set({ page: 1, puskesmasId: "", status: "" }),
}));
