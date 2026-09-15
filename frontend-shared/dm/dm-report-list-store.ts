"use client";

import { create } from "zustand";

type State = {
  // Registry filters (per CLAUDE.md §7.12 — survives detail navigation).
  puskesmasId: string;
  year: number;
  q: string;
  page: number;
  setPuskesmasId: (id: string) => void;
  setYear: (y: number) => void;
  setQ: (q: string) => void;
  setPage: (p: number) => void;
  reset: () => void;
};

const _NOW_YEAR = new Date().getFullYear();

// Separate from the hipertensi store on purpose: the two registries are
// different pages, and a puskesmas/year picked on one must not silently
// re-scope the other.
export const useDmReportListStore = create<State>((set) => ({
  puskesmasId: "",
  year: _NOW_YEAR,
  q: "",
  page: 1,
  setPuskesmasId: (puskesmasId) => set({ puskesmasId, page: 1 }),
  setYear: (year) => set({ year, page: 1 }),
  setQ: (q) => set({ q, page: 1 }),
  setPage: (page) => set({ page }),
  reset: () => set({ puskesmasId: "", year: _NOW_YEAR, q: "", page: 1 }),
}));
