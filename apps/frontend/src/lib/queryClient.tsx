"use client";

// ARCH-P2 #828: TanStack Query client foundation (MOD-013 observability read-side).
// One configured client shared by every route via QueryProvider.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { ApiError } from "@/lib/api-errors";

export interface QueryClientDefaults {
  staleTime: number;
  gcTime: number;
  refetchOnWindowFocus: boolean;
  retry: number | ((failureCount: number, error: unknown) => boolean);
  refetchOnReconnect: boolean;
}

/**
 * Retry once, but only for transient failures (api-standards §5): a network
 * error or a 5xx. A 4xx is a definite answer, so retrying it only delays the
 * error the user needs to see.
 */
export function retryTransient(failureCount: number, error: unknown): boolean {
  if (failureCount >= 1) return false;
  if (error instanceof ApiError && error.status !== undefined) {
    return error.status >= 500;
  }
  return true;
}

export const QUERY_CLIENT_DEFAULTS: QueryClientDefaults = {
  staleTime: 30_000,
  gcTime: 5 * 60_000,
  refetchOnWindowFocus: false,
  retry: retryTransient,
  refetchOnReconnect: true,
};

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: QUERY_CLIENT_DEFAULTS.staleTime,
        gcTime: QUERY_CLIENT_DEFAULTS.gcTime,
        refetchOnWindowFocus: QUERY_CLIENT_DEFAULTS.refetchOnWindowFocus,
        retry: QUERY_CLIENT_DEFAULTS.retry,
        refetchOnReconnect: QUERY_CLIENT_DEFAULTS.refetchOnReconnect,
      },
    },
  });
}

let browserQueryClient: QueryClient | undefined;

export function getQueryClient(): QueryClient {
  if (typeof window === "undefined") {
    return makeQueryClient();
  }
  if (!browserQueryClient) {
    browserQueryClient = makeQueryClient();
  }
  return browserQueryClient;
}

export const queryClient = getQueryClient();

export function QueryProvider({ children }: { children: ReactNode }) {
  const client = getQueryClient();
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

export default QueryProvider;
