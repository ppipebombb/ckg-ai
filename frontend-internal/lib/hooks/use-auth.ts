"use client";

import { useEffect } from "react";
import { create } from "zustand";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { jwtDecode } from "jwt-decode";
import { adminLogin, adminLogout, adminMe } from "@/lib/api/auth";
import {
  clearAuth,
  readAuth,
  writeAuth,
  type StoredAuth,
} from "@/lib/auth/storage";

type AuthState = {
  hydrated: boolean;
  auth: StoredAuth | null;
  setAuth: (a: StoredAuth | null) => void;
  hydrate: () => void;
};

export const useAuthStore = create<AuthState>((set) => ({
  hydrated: false,
  auth: null,
  setAuth: (a) => set({ auth: a }),
  hydrate: () => set({ auth: readAuth(), hydrated: true }),
}));

export function useAuthHydration() {
  const hydrate = useAuthStore((s) => s.hydrate);
  useEffect(() => {
    hydrate();
  }, [hydrate]);
}

export function useAuth() {
  const auth = useAuthStore((s) => s.auth);
  const hydrated = useAuthStore((s) => s.hydrated);
  return { auth, hydrated };
}

export function useLogin() {
  const setAuth = useAuthStore((s) => s.setAuth);
  return useMutation({
    mutationFn: adminLogin,
    onSuccess: (data) => {
      const decoded = jwtDecode<{ exp: number }>(data.access_token);
      const stored: StoredAuth = { token: data.access_token, exp: decoded.exp };
      writeAuth(stored);
      setAuth(stored);
    },
  });
}

export function useLogout() {
  const setAuth = useAuthStore((s) => s.setAuth);
  const qc = useQueryClient();
  return async () => {
    // Revoke server-side BEFORE clearing local state (the axios interceptor
    // needs the token still present to authenticate the logout call). Best-effort:
    // a network/Redis failure must not block the user from logging out locally.
    try {
      await adminLogout();
    } catch {
      // ignore — proceed with local logout
    }
    clearAuth();
    setAuth(null);
    qc.clear();
  };
}

export const meKeys = {
  me: ["admin", "me"] as const,
};

export function useAdminMe(enabled: boolean) {
  return useQuery({
    queryKey: meKeys.me,
    queryFn: adminMe,
    enabled,
    staleTime: Infinity,
  });
}
