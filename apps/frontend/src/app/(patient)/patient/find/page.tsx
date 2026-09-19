"use client";

// PHASE-8.1 T11 (#485): the /patient/find route (blueprint §5.3) - the
// patient shell's live Find Care page. It was the nav's dead link (no page
// today); after this ticket the patient nav is honest: Find browses the
// verified directory and Inbox/Bookings stay dimmed. The interactive surface
// is the FindCareBrowser client leaf (continuation CTA + DirectoryBrowser) -
// it reads the URL's ?intake param via useSearchParams, so it needs a
// Suspense boundary during static prerender (same pattern as /login).

import { Suspense } from "react";

import { FindCareBrowser } from "@/components/patient/find/FindCareBrowser";

export default function FindPage() {
  return (
    <Suspense fallback={null}>
      <FindCareBrowser />
    </Suspense>
  );
}
