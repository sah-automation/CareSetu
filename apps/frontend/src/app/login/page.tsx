"use client";

// PHASE-2.5 T6 (#152): Login page with role-based redirect.
// Renders the phone+OTP auth flow extracted from PatientAuthWizard. If the
// shared session context reports an authenticated user, redirects to their
// role dashboard instead of showing the login form.

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { PatientAuthWizard } from "@/components/auth/otp/PatientAuthWizard";
import { useAuth } from "@/lib/auth/AuthContext";

export default function LoginPage() {
  const router = useRouter();
  const { isAuthenticated } = useAuth();

  useEffect(() => {
    if (isAuthenticated) {
      router.replace("/patient");
    }
  }, [isAuthenticated, router]);

  return <PatientAuthWizard />;
}
