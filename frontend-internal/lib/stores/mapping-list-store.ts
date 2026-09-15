"use client";

import { create } from "zustand";

type Coverage = "" | "covered" | "partial" | "none";

type State = {
  page: number;
  q: string;
  coverage: Coverage;
  hasAudit: "" | "yes" | "no";
  setPage: (p: number) => void;
  setQ: (q: string) => void;
  setCoverage: (c: Coverage) => void;
  setHasAudit: (h: "" | "yes" | "no") => void;
  reset: () => void;
};

export const useMappingListStore = create<State>((set) => ({
  page: 1,
  q: "",
  coverage: "",
  hasAudit: "",
  setPage: (page) => set({ page }),
  setQ: (q) => set({ q, page: 1 }),
  setCoverage: (coverage) => set({ coverage, page: 1 }),
  setHasAudit: (hasAudit) => set({ hasAudit, page: 1 }),
  reset: () => set({ page: 1, q: "", coverage: "", hasAudit: "" }),
}));
