import type { NextConfig } from "next";

// Fail the Vercel production build loudly if the backend base URL is missing,
// instead of shipping a site that silently falls back to http://localhost:8000
// (deployment plan section 7.1, POST-DEPLOY-OPTS). VERCEL is set by Vercel
// during builds only, so local `next dev` and GitHub CI builds are unaffected.
if (process.env.VERCEL && !process.env.NEXT_PUBLIC_API_BASE_URL) {
  throw new Error(
    "NEXT_PUBLIC_API_BASE_URL is not set - configure it in the Vercel project env vars",
  );
}

// NFR-SEC-001 (TEST-B2, #136): every external response must carry
// X-Content-Type-Options: nosniff. Set here in Next headers (applies to all
// routes including the root not-found page) in addition to vercel.json.
// CSP report-only (PHASE-14B Batch 2, #775): Content-Security-Policy-Report-Only
// with reporting directives when NEXT_PUBLIC_CSP_REPORT_URI is set at build time.
// The policy matches the current Next.js application: self-hosted assets, the API
// origin, inline styles and scripts required by the framework, data and blob
// images, no objects, no framing.
const apiOrigin =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const cspReportUri = process.env.NEXT_PUBLIC_CSP_REPORT_URI;

const cspDirectives = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline' 'unsafe-eval' ${apiOrigin}`,
  `style-src 'self' 'unsafe-inline' ${apiOrigin}`,
  "img-src 'self' data: blob:",
  "font-src 'self'",
  `connect-src 'self' ${apiOrigin}`,
  "frame-ancestors 'none'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
];

const cspHeaderValue =
  cspDirectives.join("; ") +
  (cspReportUri ? `; report-uri ${cspReportUri}` : "");

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  ...(cspReportUri
    ? [
        { key: "Content-Security-Policy-Report-Only", value: cspHeaderValue },
        { key: "Reporting-Endpoints", value: `csp-endpoint="${cspReportUri}"` },
      ]
    : []),
];

const nextConfig: NextConfig = {
  headers: async () => [
    {
      source: "/(.*)",
      headers: securityHeaders,
    },
  ],
};

export default nextConfig;
