// PHASE-2.6 T12 (#203): session-scoped, per-request consent-denial memory
// backing the "never re-prompts aggressively" rule (blueprint §5.10). A Not-
// now on a consent-moment sheet marks its request key here; host surfaces
// consult the mark to keep the denial conversation standing instead of
// restarting it. Deliberately in-memory: it dies with the page session and
// never pretends a server-side preference exists - grant/revoke persistence
// is a later-phase integration point, not faked here.

type RequestKey = string;

const deniedRequests = new Set<RequestKey>();

export function markDenied(requestKey: RequestKey): void {
  deniedRequests.add(requestKey);
}

export function hasBeenDenied(requestKey: RequestKey): boolean {
  return deniedRequests.has(requestKey);
}

// A later Allow supersedes the standing denial: without this, a session that
// went Not-now then Allow would keep showing the denial conversation even
// though the recorded decision flipped.
export function clearDenied(requestKey: RequestKey): void {
  deniedRequests.delete(requestKey);
}

// Test isolation only: the store is process-global.
export function __resetConsentGateForTests(): void {
  deniedRequests.clear();
}
