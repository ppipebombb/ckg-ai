"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/hooks/use-auth";

export default function RootPage() {
  const { auth, hydrated } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!hydrated) return;
    router.replace(auth ? "/dashboard" : "/login");
  }, [hydrated, auth, router]);

  return (
    <div className="flex h-screen items-center justify-center text-sm text-[var(--muted-foreground)]">
      Loading…
    </div>
  );
}
