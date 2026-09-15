"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/hooks/use-auth";

export function RequireAuth({
  children,
  redirectTo = "/login",
}: {
  children: React.ReactNode;
  redirectTo?: string;
}) {
  const { auth, hydrated } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (hydrated && !auth) {
      router.replace(redirectTo);
    }
  }, [hydrated, auth, router, redirectTo]);

  if (!hydrated) {
    return (
      <div className="flex h-screen items-center justify-center text-sm text-[var(--muted-foreground)]">
        Loading…
      </div>
    );
  }
  if (!auth) return null;
  return <>{children}</>;
}
