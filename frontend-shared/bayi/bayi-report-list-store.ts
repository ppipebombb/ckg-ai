"use client";

import { create } from "zustand";

type State = {
  // Shared by both Bayi Kuning sheets (Ikterus / Ikterus Berat) — they are the
  // same registry viewed by band, so a puskesmas/year picked on one carries to
  // the other. Per CLAUDE.md §7.12 (survives detail navigation).
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

export const useBayiReportListStore = create<State>((set) => ({
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
