// PHASE-2.6 T09 (#200): forward-link constants for the public chrome. The
// directory pages (/directory) and the provider-registration wizard route
// (/staff/register - public carve-out of the staff group, see proxy.ts)
// arrive in later tickets; the homepage lands these hrefs now so the CTA
// targets are stable when those surfaces ship (brief handoff notes).

export const DIRECTORY_ROUTE = "/directory";
export const PROVIDER_REGISTER_ROUTE = "/staff/register";
export const PATIENT_LOGIN_ROUTE = "/login";

// The three supply-side provider classes across the whole public chrome -
// directory filters, chips/tiles presets, and registration presets.
export type ProviderType = "doctor" | "lab" | "chemist";

// Directory links pre-seed filters (blueprint §3.1): tiles/chips carry the
// provider type plus, for chips, the specialty as the free-text query.
export function directoryHref(
  providerType?: ProviderType,
  query?: string,
): string {
  const params = new URLSearchParams();
  if (providerType) params.set("type", providerType);
  if (query) params.set("q", query);
  const qs = params.toString();
  return qs ? `${DIRECTORY_ROUTE}?${qs}` : DIRECTORY_ROUTE;
}

// Providers-band / footer CTAs carry the application-type preset consumed by
// ticket 11's wizard (FEAT-014 open registration).
export function providerRegisterHref(providerType: ProviderType): string {
  return `${PROVIDER_REGISTER_ROUTE}?type=${encodeURIComponent(providerType)}`;
}
