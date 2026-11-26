// PHASE-6 T05a (#317): public directory browse page at /directory
// (blueprint §2.1 public URL group, PROTO-PHASE-6 finalized views as the
// visual binding). Public server page for SEO + metadata; the interactive
// surface is a client leaf (search, filter chips, result cards, wider-area
// fallback) so every node re-renders through the i18n engine. Not guarded by
// src/proxy.ts - the cookie guard only matches app route groups. Type-preset
// variants (/doctors, /labs, /chemists) and homepage wiring are #318.

import type { Metadata } from "next";
import { Suspense } from "react";

import { DirectoryBrowser } from "@/components/directory/DirectoryBrowser";
import { PublicFooter } from "@/components/public/PublicFooter";
import { PublicHeader } from "@/components/public/PublicHeader";

export const metadata: Metadata = {
  title: "Find verified providers in Daltonganj - CareSetu",
  description:
    "Search doctors, labs and chemists near you. Only activated, verified providers are listed.",
};

export default function DirectoryPage() {
  return (
    <>
      <PublicHeader />
      {/* useSearchParams needs a Suspense boundary during static prerender. */}
      <Suspense fallback={null}>
        <DirectoryBrowser />
      </Suspense>
      <PublicFooter />
    </>
  );
}
