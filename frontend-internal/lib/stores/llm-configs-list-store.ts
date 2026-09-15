"use client";

import { create } from "zustand";

type State = {
  page: number;
  label: string;
  setPage: (p: number) => void;
  setLabel: (l: string) => void;
  reset: () => void;
};

export const useLlmConfigsListStore = create<State>((set) => ({
  page: 1,
  label: "",
  setPage: (page) => set({ page }),
  setLabel: (label) => set({ label, page: 1 }),
  reset: () => set({ page: 1, label: "" }),
}));
