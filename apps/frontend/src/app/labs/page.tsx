// PHASE-6 T05b (#318): public type-preset directory variant at /labs
// (blueprint §2.1 public URL group). Thin wrapper over the #317 browse
// surface (/directory) with the partner type pinned - the browser's
// `presetType` prop keeps the type chips off and the URL commits on this
// route. Public server page for SEO + metadata; the interactive surface is
// the shared DirectoryBrowser client leaf. Not guarded by src/proxy.ts.

import type { Metadata } from "next";
import { Suspense } from "react";

import { DirectoryBrowser } from "@/components/directory/DirectoryBrowser";
import { PublicFooter } from "@/components/public/PublicFooter";
import { PublicHeader } from "@/components/public/PublicHeader";

export const metadata: Metadata = {
  title: "Find verified labs near you - CareSetu",
  description:
    "Search verified labs in Daltonganj. Only activated, verified providers are listed.",
};

export default function LabsPage() {
  return (
    <>
      <PublicHeader />
      {/* presetType pins the partner type; useSearchParams still needs a
          Suspense boundary during static prerender. */}
      <Suspense fallback={null}>
        <DirectoryBrowser presetType="lab" />
      </Suspense>
      <PublicFooter />
    </>
  );
}
