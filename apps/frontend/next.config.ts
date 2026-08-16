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
const securityHeaders = [{ key: "X-Content-Type-Options", value: "nosniff" }];

const nextConfig: NextConfig = {
  headers: async () => [
    {
      source: "/(.*)",
      headers: securityHeaders,
    },
  ],
};

export default nextConfig;
