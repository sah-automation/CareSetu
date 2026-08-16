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

const nextConfig: NextConfig = {};

export default nextConfig;
