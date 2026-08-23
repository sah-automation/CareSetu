// PHASE-2.6 T07 (#198): cookie-presence guard on app routes (ADR-0005).
//
// The guard checks ONLY that a secret-free, client-written presence-hint
// cookie (`caresetu_authed`, maintained by saveSession/clearSession in
// lib/auth/session) is present and non-empty - it never decodes JWT claims.
// The hint lives on THIS origin because the backend's own Set-Cookie lands
// on the API origin and cannot reach the frontend on split deployments
// (Vercel frontend -> Render backend); see the ADR-0005 amendment.
// Unauthenticated hits on an app route redirect to that group's entry point
// (blueprint §2.2): patient deep links re-enter via the patient OTP wizard
// (/login), staff groups via /staff/login (built in ticket 10; 404 until
// then). The original path+query rides along as the `return` param so deep
// links never dead-end. Wrong-role/unauthenticated enforcement beyond this
// is client-side UX; real authorization stays at the API gateway RBAC.

import { NextRequest, NextResponse } from "next/server";

import { HINT_COOKIE } from "@/lib/auth/session";
import { RETURN_PARAM } from "@/lib/auth/return-url";

// Staff entry point, built in PHASE-2.6 T10 (#201). Pointed at now so the
// redirect contract is stable; until then a signed-out staff-group hit 404s
// after the redirect instead of dead-ending silently.
const STAFF_LOGIN = "/staff/login";

interface AppGroup {
  prefix: string;
  entry: string;
}

// App-route prefix -> group-correct entry point (blueprint §2.1/§4.5).
// Order-independent: prefixes are disjoint. Public carve-outs under these
// prefixes (e.g. /staff/register going public in ticket 11) belong in the
// matcher below plus an explicit pass-through here - keep both tables easy
// to extend.
const APP_GROUPS: readonly AppGroup[] = [
  { prefix: "/patient", entry: "/login" },
  { prefix: "/doctor", entry: STAFF_LOGIN },
  { prefix: "/partner", entry: STAFF_LOGIN },
  { prefix: "/operator", entry: STAFF_LOGIN },
];

function matchesAppGroup(pathname: string): AppGroup | null {
  for (const group of APP_GROUPS) {
    if (pathname === group.prefix || pathname.startsWith(`${group.prefix}/`)) {
      return group;
    }
  }
  return null;
}

function hasSessionCookie(request: NextRequest): boolean {
  const value = request.cookies.get(HINT_COOKIE)?.value;
  return typeof value === "string" && value.length > 0;
}

export function proxy(request: NextRequest): NextResponse {
  if (hasSessionCookie(request)) {
    return NextResponse.next();
  }

  const group = matchesAppGroup(request.nextUrl.pathname);
  if (!group) {
    return NextResponse.next();
  }

  const entry = request.nextUrl.clone();
  entry.pathname = group.entry;
  // Drop the original query from the entry URL (it rides inside the return
  // param instead) so no stray params leak onto the entry surface. Sanitize
  // on read: the shared helper rejects off-site targets, so `return` can
  // never open-redirect.
  entry.search = "";
  entry.searchParams.set(
    RETURN_PARAM,
    `${request.nextUrl.pathname}${request.nextUrl.search}`,
  );

  return NextResponse.redirect(entry);
}

export const config = {
  // Only app routes run through the guard; static assets, public chrome,
  // /login and /choose-role never invoke it.
  matcher: [
    "/patient/:path*",
    "/doctor/:path*",
    "/partner/:path*",
    "/operator/:path*",
  ],
};
