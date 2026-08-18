"use client";

// PHASE-2.5 T6 (#152): Login page with role-based redirect.
// Renders the phone+OTP auth flow extracted from PatientAuthWizard. If the user
// is already authenticated (valid session in localStorage), redirects to their
// role dashboard instead of showing the login form.

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { PatientAuthWizard } from "@/components/auth/otp/PatientAuthWizard";
import { readSession } from "@/lib/auth/session";

export default function LoginPage() {
  const router = useRouter();

  useEffect(() => {
    const session = readSession();
    if (session) {
      router.replace("/patient");
    }
  }, [router]);

  return <PatientAuthWizard />;
}
