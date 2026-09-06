// PHASE-6 T06 (#312): public provider-profile page at /providers/[id]
// (blueprint §2.1 public URL group - `/providers/:id`; §3.1 row 5). Public
// server page for SEO + metadata; the interactive surface is the
// ProviderProfile client leaf. No auth guard (not matched by src/proxy.ts).
// The page renders only the verified-safe fields the profile API returns -
// never raw credential documents, emails, phones or PHI.

import type { Metadata } from "next";

import { PublicFooter } from "@/components/public/PublicFooter";
import { PublicHeader } from "@/components/public/PublicHeader";
import { ProviderProfile } from "@/components/public/ProviderProfile";

export const metadata: Metadata = {
  title: "Provider profile - CareSetu",
  description:
    "Verified provider credentials, licence status and service area. Only activated providers with valid credentials are shown.",
};

interface ProvidersProfilePageProps {
  params: Promise<{ id: string }>;
}

export default async function ProvidersProfilePage({
  params,
}: ProvidersProfilePageProps) {
  const { id } = await params;
  const partnerId = Number(id);

  return (
    <>
      <PublicHeader />
      <ProviderProfile partnerId={Number.isFinite(partnerId) ? partnerId : 0} />
      <PublicFooter />
    </>
  );
}
