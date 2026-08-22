/**
 * Resolved public homepage - PHASE-2.6 T09 (#200), spec #191 decision 10,
 * blueprint §3.1. Replaces the Phase 2.5 marketing placeholder.
 *
 * Server component for SEO; the ten ordered sections are client leaves so
 * every public copy node re-renders through the i18n engine and the header
 * auth button reads session truth from root AuthContext:
 *
 *   1 header | 2 hero + directory search | 3 specialty chips
 *   4 category tiles | 5 featured doctor cards | 6 how-it-works
 *   7 trust & consent strip | 8 providers band | 9 final CTA | 10 footer
 *
 * Copy rules baked in: categories are marketing navigation over specialties -
 * no disease-based program promises (gap G1); featured cards render live data
 * when supply exists, else the honest "Directory launching soon" empty state
 * (gap G2).
 */
import type { Metadata } from "next";

import { CategoryTiles } from "@/components/public/CategoryTiles";
import { FeaturedDoctors } from "@/components/public/FeaturedDoctors";
import { FinalCtaBand } from "@/components/public/FinalCtaBand";
import { HeroSearch } from "@/components/public/HeroSearch";
import { HowItWorks } from "@/components/public/HowItWorks";
import { ProvidersBand } from "@/components/public/ProvidersBand";
import { PublicFooter } from "@/components/public/PublicFooter";
import { PublicHeader } from "@/components/public/PublicHeader";
import { SpecialtyChips } from "@/components/public/SpecialtyChips";
import { TrustStrip } from "@/components/public/TrustStrip";

export const metadata: Metadata = {
  title: "CareSetu - Find trusted doctors, labs and chemists near you",
  description:
    "Book visits, share reports and keep every record in one place - shared only with your consent.",
};

export default function MarketingHomepage() {
  return (
    <>
      <PublicHeader />
      <main>
        <HeroSearch />
        <SpecialtyChips />
        <CategoryTiles />
        <FeaturedDoctors />
        <HowItWorks />
        <TrustStrip />
        <ProvidersBand />
        <FinalCtaBand />
      </main>
      <PublicFooter />
    </>
  );
}
