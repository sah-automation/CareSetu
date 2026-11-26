// PHASE-2.6 T09 (#200): forward-link constants for the public chrome. The
// directory pages (/directory) and the provider-registration wizard route
// (/staff/register - public carve-out of the staff group, see proxy.ts)
// arrive in later tickets; the homepage lands these hrefs now so the CTA
// targets are stable when those surfaces ship (brief handoff notes).

export const DIRECTORY_ROUTE = "/directory";
export const PROVIDER_PROFILE_ROUTE = "/providers";
export const PROVIDER_REGISTER_ROUTE = "/staff/register";
export const PATIENT_LOGIN_ROUTE = "/login";

// Builds the public provider-profile href for a partner id (blueprint §3.1
// row 5, `/providers/:id`). `provider` is the display word legal in this
// route's copy; `partner` stays the domain word everywhere in data (glossary).
export function providerProfileHref(partnerId: number): string {
  return `${PROVIDER_PROFILE_ROUTE}/${partnerId}`;
}

// The three supply-side provider classes across the whole public chrome -
// directory filters, chips/tiles presets, and registration presets.
export type ProviderType = "doctor" | "lab" | "chemist";

// PHASE-6 T05b (#318): canonical URL for each type-preset directory variant
// (blueprint §2.1 public URL group). The /directory route stays the
// type-mutable "all" browse surface; these routes pin the type for SEO and
// per-type deep links.
export const DIRECTORY_VARIANT_ROUTES: Record<ProviderType, string> = {
  doctor: "/doctors",
  lab: "/labs",
  chemist: "/chemists",
};

// Directory links pre-seed filters (blueprint §3.1): tiles carry the provider
// type, chips carry the provider type plus a text filter.
//
// #623: those two text filters are NOT the same parameter and must not share a
// positional one. `q` is the backend's free-text search, which matches across a
// practice name, clinic name and area; `specialty` is the closed-vocabulary
// membership filter, which matches a doctor declaring that specialty. Sending a
// specialty as `q` searches for that word in three columns instead of filtering
// on the one that matters, so a homepage chip for a doctor filtered on
// "Cardiologist" returned every partner whose name or area happened to contain
// the string and silently dropped the filter UI. An options bag rather than a
// third positional argument, so a caller cannot express one of the two by
// accident and the compiler rejects an unknown filter name.
export interface DirectoryFilters {
  /** Free-text search across name, clinic name and area. */
  q?: string;
  /** Closed-vocabulary specialty membership. Doctors only. */
  specialty?: string;
}

export function directoryHref(
  providerType?: ProviderType,
  filters?: DirectoryFilters,
): string {
  const params = new URLSearchParams();
  if (providerType) params.set("type", providerType);
  if (filters?.q) params.set("q", filters.q);
  if (filters?.specialty) params.set("specialty", filters.specialty);
  const qs = params.toString();
  return qs ? `${DIRECTORY_ROUTE}?${qs}` : DIRECTORY_ROUTE;
}

// Providers-band / footer CTAs carry the application-type preset consumed by
// ticket 11's wizard (FEAT-014 open registration).
export function providerRegisterHref(providerType: ProviderType): string {
  return `${PROVIDER_REGISTER_ROUTE}?type=${encodeURIComponent(providerType)}`;
}
