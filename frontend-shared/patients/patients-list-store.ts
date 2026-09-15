"use client";

import { format } from "date-fns";
import { create } from "zustand";

function today(): string {
  // Local date — patient.filter_date is the local scrape date, so UTC slice would mismatch around midnight WIB.
  return format(new Date(), "yyyy-MM-dd");
}

type MergedFilter = "all" | "merged" | "unmerged";

type State = {
  page: number;
  q: string;
  puskesmasId: string;
  filterDate: string;
  matchStatus: string;
  merged: MergedFilter;
  // umur/age range — kept as strings (raw input); empty = unset. Each setter
  // resets page to 1 (per the list-filter convention).
  minAge: string;
  maxAge: string;
  setPage: (p: number) => void;
  setQ: (q: string) => void;
  setPuskesmasId: (id: string) => void;
  setFilterDate: (d: string) => void;
  setMatchStatus: (s: string) => void;
  setMerged: (m: MergedFilter) => void;
  setMinAge: (a: string) => void;
  setMaxAge: (a: string) => void;
  reset: () => void;
};

const initial = {
  page: 1,
  q: "",
  puskesmasId: "",
  filterDate: today(),
  matchStatus: "",
  merged: "all" as MergedFilter,
  minAge: "",
  maxAge: "",
};

export const usePatientsListStore = create<State>((set) => ({
  ...initial,
  setPage: (page) => set({ page }),
  setQ: (q) => set({ q, page: 1 }),
  setPuskesmasId: (puskesmasId) => set({ puskesmasId, page: 1 }),
  setFilterDate: (filterDate) => set({ filterDate, page: 1 }),
  setMatchStatus: (matchStatus) => set({ matchStatus, page: 1 }),
  setMerged: (merged) => set({ merged, page: 1 }),
  setMinAge: (minAge) => set({ minAge, page: 1 }),
  setMaxAge: (maxAge) => set({ maxAge, page: 1 }),
  reset: () => set({ ...initial, filterDate: today() }),
}));
