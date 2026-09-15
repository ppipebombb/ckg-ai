"use client";

import { create } from "zustand";

type State = {
  page: number;
  q: string;
  puskesmasId: string;
  status: string; // "" = all, else belum/sedang/selesai
  schoolName: string;
  className: string;
  schoolYear: string; // raw; "" = all
  minAge: string;
  maxAge: string;
  setPage: (p: number) => void;
  setQ: (q: string) => void;
  setPuskesmasId: (id: string) => void;
  setStatus: (s: string) => void;
  setSchoolName: (s: string) => void;
  setClassName: (s: string) => void;
  setSchoolYear: (y: string) => void;
  setMinAge: (a: string) => void;
  setMaxAge: (a: string) => void;
  reset: () => void;
};

const initial = {
  page: 1,
  q: "",
  puskesmasId: "",
  status: "",
  schoolName: "",
  className: "",
  schoolYear: "",
  minAge: "",
  maxAge: "",
};

export const useSchoolPatientsListStore = create<State>((set) => ({
  ...initial,
  setPage: (page) => set({ page }),
  setQ: (q) => set({ q, page: 1 }),
  // Changing puskesmas invalidates the school/class facet selections.
  setPuskesmasId: (puskesmasId) =>
    set({ puskesmasId, schoolName: "", className: "", page: 1 }),
  setStatus: (status) => set({ status, page: 1 }),
  // Pilih Sekolah resets the cascading Kelas selection.
  setSchoolName: (schoolName) => set({ schoolName, className: "", page: 1 }),
  setClassName: (className) => set({ className, page: 1 }),
  setSchoolYear: (schoolYear) => set({ schoolYear, page: 1 }),
  setMinAge: (minAge) => set({ minAge, page: 1 }),
  setMaxAge: (maxAge) => set({ maxAge, page: 1 }),
  reset: () => set({ ...initial }),
}));
