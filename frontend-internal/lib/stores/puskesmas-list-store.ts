"use client";

import { create } from "zustand";

type State = {
  page: number;
  name: string;
  setPage: (p: number) => void;
  setName: (n: string) => void;
  reset: () => void;
};

export const usePuskesmasListStore = create<State>((set) => ({
  page: 1,
  name: "",
  setPage: (page) => set({ page }),
  setName: (name) => set({ name, page: 1 }),
  reset: () => set({ page: 1, name: "" }),
}));
