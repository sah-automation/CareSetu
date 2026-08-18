import { NextRequest, NextResponse } from "next/server";

const COOKIE_NAME = "caresetu_session";

const PROTECTED_ROUTES = ["/patient", "/partner", "/operator"];

function isProtectedRoute(pathname: string): boolean {
  return PROTECTED_ROUTES.some(
    (route) => pathname === route || pathname.startsWith(`${route}/`),
  );
}

export function proxy(request: NextRequest, _event?: never) {
  const { pathname } = request.nextUrl;
  const hasSession = request.cookies.get(COOKIE_NAME)?.value !== undefined;

  if (isProtectedRoute(pathname) && !hasSession) {
    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = "/login";
    return NextResponse.redirect(loginUrl);
  }

  if (pathname === "/login" && hasSession) {
    const dashboardUrl = request.nextUrl.clone();
    dashboardUrl.pathname = "/patient";
    return NextResponse.redirect(dashboardUrl);
  }

  if (pathname === "/choose-role" && !hasSession) {
    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = "/login";
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/patient/:path*",
    "/partner/:path*",
    "/operator/:path*",
    "/login",
    "/choose-role",
  ],
};
