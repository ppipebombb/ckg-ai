"use client";

import { QueryClient } from "@tanstack/react-query";

let _client: QueryClient | null = null;

export function getQueryClient() {
  if (!_client) {
    _client = new QueryClient({
      defaultOptions: {
        queries: {
          staleTime: 30_000,
          refetchOnWindowFocus: false,
          retry: 1,
        },
        mutations: { retry: 0 },
      },
    });
  }
  return _client;
}
