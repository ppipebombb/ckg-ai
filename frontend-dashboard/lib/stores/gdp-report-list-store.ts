"use client";

import { create } from "zustand";

type GdpTab = "report" | "diagnose";

type State = {
  // Dashboard filters (per CLAUDE.md §7.12 — survives detail navigation).
  puskesmasId: string;
  year: number;
  q: string;
  ckgOnly: boolean;
  page: number;
  // Active dashboard tab — survives detail navigation alongside the filters.
  tab: GdpTab;
  setPuskesmasId: (id: string) => void;
  setYear: (y: number) => void;
  setQ: (q: string) => void;
  setCkgOnly: (v: boolean) => void;
  setPage: (p: number) => void;
  setTab: (t: GdpTab) => void;
  reset: () => void;
};

const _NOW_YEAR = new Date().getFullYear();

export const useGdpReportListStore = create<State>((set) => ({
  puskesmasId: "",
  year: _NOW_YEAR,
  q: "",
  ckgOnly: true,
  page: 1,
  tab: "report",
  setPuskesmasId: (puskesmasId) => set({ puskesmasId, page: 1 }),
  setYear: (year) => set({ year, page: 1 }),
  setQ: (q) => set({ q, page: 1 }),
  setCkgOnly: (ckgOnly) => set({ ckgOnly, page: 1 }),
  setPage: (page) => set({ page }),
  setTab: (tab) => set({ tab }),
  reset: () =>
    set({
      puskesmasId: "",
      year: _NOW_YEAR,
      q: "",
      ckgOnly: true,
      page: 1,
      tab: "report",
    }),
}));
