"use client";

// PHASE-2.5 T6 (#152): Login page with role-based redirect.
// Renders the phone+OTP auth flow extracted from PatientAuthWizard. If the
// shared session context reports an authenticated user, redirects to their
// role dashboard instead of showing the login form.
//
// PHASE-2.6 T07 (#198): honors the proxy's `return` param (blueprint §2.2) -
// a signed-out deep link to a patient app route lands here with
// ?return=<original>, and both the already-signed-in redirect and the
// post-OTP landing go back there instead of hard-coding /patient.

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { PatientAuthWizard } from "@/components/auth/otp/PatientAuthWizard";
import { RETURN_PARAM, sanitizeReturnTarget } from "@/lib/auth/return-url";
import { useAuth } from "@/lib/auth/AuthContext";

function LoginView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { isAuthenticated } = useAuth();
  const returnTo = sanitizeReturnTarget(searchParams.get(RETURN_PARAM));

  useEffect(() => {
    if (isAuthenticated) {
      router.replace(returnTo);
    }
  }, [isAuthenticated, returnTo, router]);

  return <PatientAuthWizard returnTo={returnTo} />;
}

export default function LoginPage() {
  // useSearchParams requires a Suspense boundary during static prerender;
  // the wizard gates its own hydration so a null fallback never flashes UI.
  return (
    <Suspense fallback={null}>
      <LoginView />
    </Suspense>
  );
}
