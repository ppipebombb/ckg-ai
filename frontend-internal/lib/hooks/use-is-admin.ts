"use client";

import { useMemo } from "react";
import { jwtDecode } from "jwt-decode";
import { useAuth } from "@/lib/hooks/use-auth";

export function useIsAdmin(): boolean {
  const { auth } = useAuth();
  return useMemo(() => {
    if (!auth?.token) return false;
    try {
      const payload = jwtDecode<{ typ?: string }>(auth.token);
      return payload.typ === "admin";
    } catch {
      return false;
    }
  }, [auth?.token]);
}
