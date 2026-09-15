"use client";

import { createContext, useContext, useSyncExternalStore } from "react";

const KEY = "ckg.sidebar.collapsed";
const EVENT = "ckg-sidebar-change";

function subscribe(cb: () => void) {
  window.addEventListener("storage", cb);
  window.addEventListener(EVENT, cb);
  return () => {
    window.removeEventListener("storage", cb);
    window.removeEventListener(EVENT, cb);
  };
}

function getSnapshot() {
  return window.localStorage.getItem(KEY) === "1";
}

function getServerSnapshot() {
  return false;
}

function writeCollapsed(v: boolean) {
  window.localStorage.setItem(KEY, v ? "1" : "0");
  window.dispatchEvent(new Event(EVENT));
}

type Ctx = {
  collapsed: boolean;
  setCollapsed: (v: boolean) => void;
  toggle: () => void;
};

const SidebarCtx = createContext<Ctx | null>(null);

export function SidebarProvider({ children }: { children: React.ReactNode }) {
  const collapsed = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const value: Ctx = {
    collapsed,
    setCollapsed: writeCollapsed,
    toggle: () => writeCollapsed(!collapsed),
  };

  return <SidebarCtx.Provider value={value}>{children}</SidebarCtx.Provider>;
}

export function useSidebar() {
  const ctx = useContext(SidebarCtx);
  if (!ctx) throw new Error("useSidebar must be used inside SidebarProvider");
  return ctx;
}
