"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { getQueryClient } from "@/lib/query/client";
import { useAuthHydration } from "@/lib/hooks/use-auth";

export function Providers({ children }: { children: React.ReactNode }) {
  useAuthHydration();
  return (
    <QueryClientProvider client={getQueryClient()}>
      {children}
      <Toaster richColors position="top-right" />
    </QueryClientProvider>
  );
}
