"use client";

// #904: the /v1/me session check becomes a cached TanStack query instead of a
// bare fetch behind AuthProvider state. The check is keyed by the JWT it was
// resolved with, so any surface that needs the identity reads the cached
// answer rather than awaiting a fresh round trip, and refresh-on-expiry stays
// handled centrally by AuthProvider's proactive-refresh timer (the timer
// rotates the token, which naturally moves the cache to the new key).

import type { QueryClient } from "@tanstack/react-query";

import { API_BASE_URL } from "@/lib/api-base";
import {
  ACCESS_TOKEN_TTL_SECONDS,
  PROACTIVE_REFRESH_RATIO,
} from "@/lib/config";

export interface MeResponse {
  /** The principal identity the token is scoped to (a numeric string, #196). */
  subject_id: string;
  phone: string;
  roles: string[];
  tier: string | null;
}

export async function fetchMe(jwt: string): Promise<MeResponse> {
  const res = await fetch(`${API_BASE_URL}/v1/me`, {
    headers: { Authorization: `Bearer ${jwt}` },
    // ADR-0005: cookie transport rides along on split-origin deploys, like
    // every other authed call in the app.
    credentials: "include",
  });
  if (!res.ok) {
    throw new Error(`GET /v1/me returned ${res.status}`);
  }
  return (await res.json()) as MeResponse;
}

export const SESSION_ME_QUERY_KEY_ROOT = ["session", "me"] as const;

export function sessionMeQueryKey(jwt: string): readonly unknown[] {
  return [...SESSION_ME_QUERY_KEY_ROOT, jwt] as const;
}

/**
 * The identity stays fresh until the central proactive refresh rotates the
 * token (80% of the access-token TTL); after rotation the new JWT resolves a
 * new key, so a revalidation fetch happens once, not on every consumer.
 */
export const SESSION_ME_STALE_TIME =
  ACCESS_TOKEN_TTL_SECONDS * 1000 * PROACTIVE_REFRESH_RATIO;

/**
 * Resolve the session identity through the shared query cache. A cached,
 * still-fresh answer answers without the network; concurrent callers share
 * one in-flight fetch. Deliberately no retry at this layer - a failed /v1/me
 * falls through to AuthProvider's refresh path, unchanged.
 */
export function fetchSessionMe(
  queryClient: QueryClient,
  jwt: string,
): Promise<MeResponse> {
  return queryClient.fetchQuery({
    queryKey: sessionMeQueryKey(jwt),
    queryFn: () => fetchMe(jwt),
    staleTime: SESSION_ME_STALE_TIME,
    // fetchQuery leaves the entry unobserved, so the default 5-minute gcTime
    // would evict it mid-window and force a refetch; the cache entry must
    // outlive the stale window for the cached check to mean anything.
    gcTime: SESSION_ME_STALE_TIME,
    retry: false,
  });
}

export function clearCachedSessionMe(queryClient: QueryClient): void {
  queryClient.removeQueries({ queryKey: SESSION_ME_QUERY_KEY_ROOT });
}
