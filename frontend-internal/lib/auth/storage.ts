"use client";

const KEY = "ckg.auth";

export type StoredAuth = { token: string; exp: number };

export function readAuth(): StoredAuth | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredAuth;
    if (!parsed.token || !parsed.exp) return null;
    if (Date.now() >= parsed.exp * 1000) {
      window.localStorage.removeItem(KEY);
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function writeAuth(auth: StoredAuth) {
  window.localStorage.setItem(KEY, JSON.stringify(auth));
}

export function clearAuth() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(KEY);
}
