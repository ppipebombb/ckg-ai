"use client";

import { create } from "zustand";

// Gap Tatalaksana filters. Its OWN store, not the registry's, because `year`
// means something different here: the year the patient ENTERED the registry
// (they stay under it until treated), not a reporting year. `undefined` = every
// year. Sharing one store would silently retarget the other page's filter.
// Per CLAUDE.md §7.12 this lives in zustand, not useState, so filters survive
// navigating away and back.
type State = {
  puskesmasId: string;
  year: number | undefined;
  q: string;
  page: number;
  setPuskesmasId: (id: string) => void;
  setYear: (y: number | undefined) => void;
  setQ: (q: string) => void;
  setPage: (p: number) => void;
  reset: () => void;
};

export const useHipertensiGapListStore = create<State>((set) => ({
  puskesmasId: "",
  year: undefined,
  q: "",
  page: 1,
  // Every filter setter resets the page — page 3 of the old filter is not
  // page 3 of the new one.
  setPuskesmasId: (puskesmasId) => set({ puskesmasId, page: 1 }),
  setYear: (year) => set({ year, page: 1 }),
  setQ: (q) => set({ q, page: 1 }),
  setPage: (page) => set({ page }),
  reset: () => set({ puskesmasId: "", year: undefined, q: "", page: 1 }),
}));
