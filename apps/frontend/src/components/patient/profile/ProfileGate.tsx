"use client";

// PHASE-2.6 T13 (#204): inline gating presentation for patient care
// actions. Per blueprint §5.9, browsing (Find Care, My Record) is never
// gated; intake/booking gates on basics; medicine-delivery checkout
// gates on area. When a gate triggers, the exact missing step of the
// profile-completion wizard is presented inline at the action moment -
// never a redirect-to-wizard dead-end. The gating explains itself
// exactly when relevant.
//
// PHASE-8.1 T2 (#488): the gate hydrates from the saved server profile
// (ProfileProvider) - a saved profile short-circuits every gate so a
// returning patient is never asked again - and the inline wizard's Finish
// persists through the profile client. The demo trigger buttons stand in
// for the real intake/booking/checkout flows that arrive in their build
// phases; the gate seam stays the same.

import { useState } from "react";
import { AlertCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { ProfileStrings } from "@/lib/i18n/dictionaries";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { ProfileCompletionWizard } from "./ProfileCompletionWizard";
import { ProfileSaveStatusNotice } from "./SaveStatusNotice";
import {
  evaluateGate,
  type PatientAction,
  type ProfileGate as GateKind,
} from "@/lib/profile/profileState";
import { useProfile } from "@/lib/profile/ProfileContext";

interface ProfileGateProps {
  /** The care action being attempted. */
  action: PatientAction;
  /** Children to render when the gate passes (or for ungated actions). */
  children: React.ReactNode;
}

export function ProfileGate({ action, children }: ProfileGateProps) {
  const { lang } = useLang();
  const t: ProfileStrings = STRINGS[lang].profile;
  const { draft, savedProfile, saveStatus, updateDraft, finishProfile } =
    useProfile();
  // Which gate opened the inline wizard, if any - doubles as the open flag.
  // Captured once at trigger time: completing a field mid-editing must never
  // re-label or yank away the open wizard. It stays up until Finish, and the
  // next render re-evaluates against the updated draft.
  const [openGate, setOpenGate] = useState<GateKind | null>(null);

  // A saved profile short-circuits every gate (#488 AC 2): the wizard was
  // finished server-side, so the gating matrix never asks again.
  if (savedProfile !== null) {
    return <>{children}</>;
  }

  const handleFinish = () => {
    void finishProfile().then((ok) => {
      if (ok) setOpenGate(null);
    });
  };

  const handleTrigger = () => {
    setOpenGate(evaluateGate(action, draft));
  };

  if (openGate !== null) {
    const gateExplain =
      openGate === "basics" ? t.gate.basicsExplain : t.gate.areaExplain;
    return (
      <div className="w-full">
        <div
          className="rounded-lg border border-hairline bg-surface p-5 shadow-card"
          data-testid={`gate-wizard-${action}`}
        >
          <div className="mb-3 flex items-center gap-2 text-sm text-txt-sub">
            <AlertCircle className="h-4 w-4 text-warm" />
            <p>{gateExplain}</p>
          </div>
          <ProfileSaveStatusNotice saveStatus={saveStatus} />
          <ProfileCompletionWizard
            draft={draft}
            onDraftChange={updateDraft}
            onFinish={handleFinish}
            initialStep={openGate === "basics" ? 1 : 3}
          />
        </div>
      </div>
    );
  }

  const gate = evaluateGate(action, draft);

  // Ungated actions render children directly
  if (gate === null) {
    return <>{children}</>;
  }

  return (
    <div className="w-full">
      <Button
        variant="outline"
        onClick={handleTrigger}
        className="w-full justify-start"
        data-testid={`gate-trigger-${action}`}
      >
        <AlertCircle className="mr-2 h-4 w-4" />
        {children}
      </Button>
    </div>
  );
}

// Demo component showing all three gate types (for the patient
// dashboard demo section)
export function ProfileGateDemo() {
  const { lang } = useLang();
  const t: ProfileStrings = STRINGS[lang].profile;

  return (
    <div className="space-y-4" data-testid="profile-gate-demo">
      <div className="text-sm font-medium text-txt">{t.demo.title}</div>
      <p className="text-sm text-txt-sub">{t.demo.body}</p>

      <div className="grid gap-4 sm:grid-cols-3">
        <ProfileGate action="intake">{t.demo.intake}</ProfileGate>
        <ProfileGate action="booking">{t.demo.booking}</ProfileGate>
        <ProfileGate action="medicineCheckout">{t.demo.checkout}</ProfileGate>
      </div>

      <p className="text-xs text-txt-muted">{t.demo.proceedNote}</p>
    </div>
  );
}
