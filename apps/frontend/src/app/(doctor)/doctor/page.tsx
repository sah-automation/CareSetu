"use client";

// PHASE-8.1 T12 (#450): doctor console landing page - replaces the Phase 5
// placeholder with the review queue (low-confidence first, oldest within each
// group, US-11/12) and open care cases (US-15). The review queue items link
// into the case workspace (review/[intakeId], cases/[caseId]); those pages are
// built by #451-#453. All copy bilingual en/hi (REQ-006).
//
// #543: the consultation-fee editor moved to the Profile page, which is where
// a doctor edits their own record; this landing keeps a compact read-only
// fee summary that links into the moved editor.
//
// #544: the coming-soon Patients/Profile tabs are replaced with real entry
// cards that deep-link to the live pages, and the whole landing adopts the
// patient shell's card/chip/empty-state/responsive design language.
//
// #676 (MOD-012 / FEAT-008): the open-cases section reads the console's
// patient-enriched cases feed (listDoctorCases) and renders the shared
// DoctorListCard the cases list and patients list use, so the dashboard and
// the cases index show exactly the same non-closed case set with the same
// card anatomy - patient name plus age, verify chip on a forced review, the
// citable case id + relative time meta line, and one whole-card link whose
// accessible name includes the patient (US-66/67).

import Link from "next/link";
import { Check, ChevronRight, Circle, Users, User } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DoctorCaseCard } from "@/components/doctor/DoctorCaseCard";
import { VerifiedBadge } from "@/components/doctor/profile/VerifiedBadge";
import { EmptyState } from "@/components/layout/EmptyState";
import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api-errors";
import {
  fetchDoctorProfile,
  listDoctorCases,
  type DoctorCaseRow,
  type DoctorProfileView,
} from "@/lib/doctor/api";
import {
  formatGreetingDate,
  greetingFirstName,
  greetingTimeText,
} from "@/lib/doctor/dashboardGreeting";
import { profileCompleteness } from "@/lib/doctor/profileCompleteness";
import { specialtyLabel } from "@/lib/directory/specialtyLabel";
import { fetchReviewQueue, type ReviewQueueItem } from "@/lib/intake/api";
import { PROFILE_ANCHORS } from "@/components/doctor/profile/ProfileSectionIndex";
import { STRINGS, type Dictionary } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { formatFeePaise } from "@/components/pick/DoctorPickCard";

// ---- helpers ----

type LoadStatus = "loading" | "ready" | "error";

function waitingSince(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const hours = Math.floor(ms / 3_600_000);
  if (hours < 1) return "<1h";
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  return days === 1 ? "1 day" : `${days} days`;
}

function confidenceDisplay(
  value: number | null,
  t: Dictionary["doctorConsole"],
): string {
  if (value == null) return "\u2014";
  return `${Math.round(value * 100)}%`;
}

function sortQueue(items: ReviewQueueItem[]): ReviewQueueItem[] {
  const sorted = [...items];
  sorted.sort((a, b) => {
    if (a.low_confidence !== b.low_confidence) return a.low_confidence ? -1 : 1;
    return new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
  });
  return sorted;
}

// ---- sub-components ----

function LoadingSkeleton() {
  return (
    <div className="space-y-3" data-testid="queue-skeleton">
      {Array.from({ length: 3 }).map((_, i) => (
        <div
          key={i}
          className="flex items-center justify-between gap-3 rounded-lg border border-hairline bg-surface p-4"
        >
          <div className="space-y-2">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-5 w-24 rounded-full" />
          </div>
          <Skeleton className="h-5 w-16 rounded-full" />
        </div>
      ))}
    </div>
  );
}

function FeeSummarySkeleton() {
  return (
    <div className="space-y-2" data-testid="fee-summary-skeleton">
      <div className="h-4 w-32 rounded bg-hairline-soft animate-pulse" />
      <div className="h-8 w-24 rounded bg-hairline-soft animate-pulse" />
    </div>
  );
}

function EntryCardSkeleton() {
  return (
    <Link
      href="#"
      aria-disabled="true"
      tabIndex={-1}
      className="pointer-events-none rounded-lg border border-hairline bg-surface p-4 min-h-24 opacity-60"
    >
      <div className="flex items-center gap-3">
        <Skeleton className="h-10 w-10 rounded-xl" />
        <div className="flex-1 space-y-1">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-3 w-32" />
        </div>
      </div>
    </Link>
  );
}

function FeeSummaryCard({ feePaise }: { feePaise: number | null }) {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorConsole;

  return (
    <section
      className="rounded-lg border border-hairline bg-surface p-4"
      data-testid="fee-summary"
    >
      <h2 className="text-[1.05rem] font-semibold text-txt">{t.feeHeading}</h2>

      {feePaise !== null ? (
        <div className="mt-2 flex flex-col items-start gap-2 min-[720px]:flex-row min-[720px]:items-center min-[720px]:justify-between">
          <p
            className="text-2xl font-semibold text-txt"
            data-testid="fee-summary-value"
          >
            {formatFeePaise(feePaise)}
          </p>
          <Link
            href="/doctor/profile#fee-editor"
            data-testid="fee-summary-edit"
            className="inline-flex items-center gap-1.5 rounded-md border border-hairline bg-surface px-3 py-1.5 text-xs font-medium text-txt-sub transition-colors hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong"
          >
            {t.feeEditAction}
            <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
          </Link>
        </div>
      ) : (
        <div className="mt-2 flex flex-col items-start gap-2 min-[720px]:flex-row min-[720px]:items-center min-[720px]:justify-between">
          <p
            className="text-2xl font-semibold text-txt-muted"
            data-testid="fee-summary-value"
          >
            {t.feeUnset}
          </p>
          <p className="text-sm text-txt-muted">{t.feeUnsetHelp}</p>
          <Link
            href="/doctor/profile#fee-editor"
            data-testid="fee-summary-edit"
            className="inline-flex items-center gap-1.5 rounded-md border border-hairline bg-surface px-3 py-1.5 text-xs font-medium text-txt-sub transition-colors hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong"
          >
            {t.feeEditAction}
            <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
          </Link>
        </div>
      )}
    </section>
  );
}

function FeeSummaryError({ onRetry }: { onRetry: () => void }) {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorConsole;

  return (
    <section
      className="rounded-lg border border-hairline bg-surface p-4"
      data-testid="fee-summary"
    >
      <h2 className="text-[1.05rem] font-semibold text-txt">{t.feeHeading}</h2>
      <div className="mt-3 flex items-center justify-between gap-3">
        <p
          className="text-sm text-danger"
          data-testid="fee-summary-error"
          role="alert"
        >
          {t.feeLoadFailed}
        </p>
        <Button
          variant="ghost"
          size="sm"
          onClick={onRetry}
          data-testid="fee-summary-retry"
        >
          {t.retry}
        </Button>
      </div>
    </section>
  );
}

// #678: the time-based greeting that opens the dashboard, replacing the generic
// console title. The doctor's own name (honorifics stripped into the first-name
// form) joins the greeting only once the profile read resolves; while it is
// still loading - or after it failed - the greeting stays name-free. Never a
// blank heading and never a skeleton: the greeting itself is stable and the
// date line beneath it always renders.
function GreetingHeader({ profile }: { profile: DoctorProfileView | null }) {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorConsole;

  const now = new Date();
  const timeGreeting = greetingTimeText(t, now);
  const firstName = profile ? greetingFirstName(profile.practice_name) : null;

  return (
    <div className="mb-6" data-testid="dashboard-greeting">
      <h1 className="text-xl font-semibold text-txt">
        {firstName ? t.greetingNamed(timeGreeting, firstName) : timeGreeting}
      </h1>
      <p className="mt-1 text-sm text-txt-muted" data-testid="greeting-date">
        {formatGreetingDate(now, lang)}
      </p>
    </div>
  );
}

// #678: the profile-status card - how the doctor's own public listing reads,
// and what is still missing from it. Verified verdict and specialty chips come
// from the same `localed` presentations the profile page uses (VerifiedBadge +
// specialtyLabel, so the dashboard and the profile cannot disagree), the fee
// reads the same projection the fee summary reads, and every gap - unverified,
// no fee, no about text, no clinic name - gets a calm hint. One whole-card
// link to the profile is where each hint gets fixed.
function ProfileStatusCard({ profile }: { profile: DoctorProfileView }) {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorConsole;
  const profileT = STRINGS[lang].doctorProfile;

  const complete = profileCompleteness(profile);
  const hints: Array<{ key: string; label: string }> = [];
  if (!complete.verified) {
    hints.push({ key: "unverified", label: t.statusHintUnverified });
  }
  if (!complete.fee) {
    hints.push({ key: "fee", label: t.feeUnsetHelp });
  }
  if (!complete.about) {
    hints.push({ key: "about", label: t.statusHintNoAbout });
  }
  if (!complete.clinic) {
    hints.push({ key: "clinic", label: t.statusHintNoClinic });
  }

  return (
    <section
      className="mt-6 rounded-lg border border-hairline bg-surface p-4"
      data-testid="profile-status"
    >
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-[1.05rem] font-semibold text-txt">
          {t.statusHeading}
        </h2>
        <Link
          href="/doctor/profile"
          data-testid="profile-status-fix"
          className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-hairline bg-surface px-3 py-1.5 text-xs font-medium text-txt-sub transition-colors hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong"
        >
          {t.statusProfileAction}
          <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
        </Link>
      </div>

      <div
        className="mt-3 flex flex-wrap items-center gap-2"
        role="group"
        aria-label={t.statusChipsLabel}
      >
        <VerifiedBadge
          verified={profile.verified}
          verifiedLabel={profileT.verified}
          notVerifiedLabel={profileT.notVerified}
          data-testid="profile-status-verified"
        />
        {profile.specialties.length === 0 ? (
          <Badge
            variant="outline"
            className="border-hairline text-txt-muted"
            data-testid="profile-status-specialties-empty"
          >
            {profileT.noSpecialtiesYet}
          </Badge>
        ) : (
          profile.specialties.map((specialty) => (
            <Badge
              key={specialty}
              variant="outline"
              className="border-hairline text-txt"
              data-testid="profile-status-specialty"
            >
              {specialtyLabel(lang, specialty)}
            </Badge>
          ))
        )}
      </div>

      <p
        className="mt-3 flex items-baseline gap-2 text-sm"
        data-testid="profile-status-fee"
      >
        <span className="font-medium text-txt">{t.feeHeading}:</span>
        <span
          className={
            profile.consultation_fee != null ? "text-txt" : "text-txt-muted"
          }
        >
          {profile.consultation_fee != null
            ? formatFeePaise(profile.consultation_fee)
            : t.feeUnset}
        </span>
      </p>

      {hints.length > 0 ? (
        <ul
          className="mt-3 border-t border-hairline-soft pt-3"
          data-testid="profile-status-hints"
        >
          {hints.map((hint) => (
            <li
              key={hint.key}
              data-testid={`profile-status-hint-${hint.key}`}
              className="flex items-start gap-2 py-1 text-sm text-txt-muted"
            >
              <Circle
                className="mt-1 h-2 w-2 shrink-0 text-warn-text"
                aria-hidden="true"
              />
              {hint.label}
            </li>
          ))}
        </ul>
      ) : (
        <p
          className="mt-3 flex items-center gap-2 border-t border-hairline-soft pt-3 text-sm text-success-text"
          data-testid="profile-status-complete"
        >
          <Check className="h-4 w-4" aria-hidden="true" />
          {t.statusComplete}
        </p>
      )}
    </section>
  );
}

function EntryCards() {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorConsole;
  const nav = STRINGS[lang].nav;

  return (
    <section className="space-y-3" data-testid="console-entries">
      <div data-testid="entry-cards" className="grid grid-cols-2 gap-3">
        <Link
          href="/doctor/patients"
          data-testid="entry-patients"
          className="flex min-h-24 flex-col items-start gap-2.5 rounded-lg border border-hairline bg-surface p-4 transition-[box-shadow,transform] hover:shadow-pop hover:-translate-y-0.5 active:scale-[0.97] active:opacity-90"
        >
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent-strong">
              <Users size={22} strokeWidth={1.8} aria-hidden="true" />
            </span>
            <div className="min-w-0 space-y-0.5">
              <span className="text-sm font-semibold text-txt">
                {nav.patients}
              </span>
              <p className="text-xs text-txt-muted line-clamp-2">
                {t.patientsEntryBody}
              </p>
            </div>
          </div>
          <ChevronRight
            className="h-5 w-5 shrink-0 text-txt-muted"
            aria-hidden="true"
          />
        </Link>
        <Link
          href="/doctor/profile"
          data-testid="entry-profile"
          className="flex min-h-24 flex-col items-start gap-2.5 rounded-lg border border-hairline bg-surface p-4 transition-[box-shadow,transform] hover:shadow-pop hover:-translate-y-0.5 active:scale-[0.97] active:opacity-90"
        >
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent-strong">
              <User size={22} strokeWidth={1.8} aria-hidden="true" />
            </span>
            <div className="min-w-0 space-y-0.5">
              <span className="text-sm font-semibold text-txt">
                {nav.profile}
              </span>
              <p className="text-xs text-txt-muted line-clamp-2">
                {t.profileEntryBody}
              </p>
            </div>
          </div>
          <ChevronRight
            className="h-5 w-5 shrink-0 text-txt-muted"
            aria-hidden="true"
          />
        </Link>
      </div>
    </section>
  );
}

// #674: the getting-started checklist for a brand-new doctor. It renders only
// when there is nothing else to work on - no open cases, an empty review
// queue - and its step states share the profile-status card's
// `profileCompleteness` projection (verified / fee / about / clinic name) so
// the two surfaces cannot disagree on what "done" means. Each step deep-links
// to the profile section where the doctor completes it.
function GettingStartedChecklist({ profile }: { profile: DoctorProfileView }) {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorConsole;

  const complete = profileCompleteness(profile);
  const steps: Array<{
    key: string;
    label: string;
    href: string;
    done: boolean;
  }> = [
    {
      key: "verified",
      label: t.checklistStepVerified,
      href: `/doctor/profile#${PROFILE_ANCHORS.verified}`,
      done: complete.verified,
    },
    {
      key: "fee",
      label: t.checklistStepFee,
      href: `/doctor/profile#${PROFILE_ANCHORS.fee}`,
      done: complete.fee,
    },
    {
      key: "about",
      label: t.checklistStepAbout,
      href: `/doctor/profile#${PROFILE_ANCHORS.about}`,
      done: complete.about,
    },
    {
      key: "clinic",
      label: t.checklistStepClinic,
      href: `/doctor/profile#${PROFILE_ANCHORS.practice}`,
      done: complete.clinic,
    },
  ];

  const stateClass = (done: boolean) =>
    done
      ? "bg-success-soft text-success-text"
      : "bg-hairline-soft text-txt-muted";

  return (
    <section
      className="mt-6 rounded-lg border border-hairline bg-surface p-4"
      data-testid="getting-started"
    >
      <div className="mb-3">
        <h2 className="text-[1.05rem] font-semibold text-txt">
          {t.checklistHeading}
        </h2>
        <p className="mt-0.5 text-sm text-txt-muted">{t.checklistBody}</p>
      </div>
      <ul className="mt-1" data-testid="checklist-steps">
        {steps.map((step) => (
          <li
            key={step.key}
            className="border-t border-hairline-soft first:border-t-0"
          >
            <Link
              href={step.href}
              data-testid={`checklist-step-${step.key}`}
              data-done={step.done}
              className="group flex items-center justify-between gap-3 rounded-md py-3 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent-border"
            >
              <span className="flex min-w-0 items-center gap-2.5">
                <span
                  aria-hidden="true"
                  className={cn(
                    "flex h-7 w-7 shrink-0 items-center justify-center rounded-full",
                    stateClass(step.done),
                  )}
                >
                  {step.done ? (
                    <Check className="h-4 w-4" />
                  ) : (
                    <Circle className="h-3.5 w-3.5" />
                  )}
                </span>
                <span className="text-sm font-medium text-txt group-hover:text-accent-strong">
                  {step.label}
                </span>
              </span>
              <span
                data-testid="checklist-step-state"
                className={cn(
                  "inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
                  stateClass(step.done),
                )}
              >
                {step.done ? t.checklistDone : t.checklistPending}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function ReviewQueueCard({
  queue,
  sortedQueue,
  loadStatus,
}: {
  queue: ReviewQueueItem[];
  sortedQueue: ReviewQueueItem[];
  loadStatus: LoadStatus;
}) {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorConsole;

  const queueReady = loadStatus === "ready";
  const queueEmpty = queueReady && sortedQueue.length === 0;

  return (
    <section
      className="rounded-lg border border-hairline bg-surface p-4"
      data-testid="review-queue"
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className="text-[1.05rem] font-semibold text-txt">
          {t.queueHeading}
        </h2>
        {queueReady && sortedQueue.length > 0 && (
          <span
            data-testid="queue-count"
            className="inline-flex items-center rounded-full bg-accent-soft px-2 py-0.5 text-xs font-medium text-accent-strong"
          >
            {sortedQueue.length}
          </span>
        )}
      </div>

      {loadStatus === "loading" && <LoadingSkeleton />}

      {queueEmpty && (
        <EmptyState title={t.queueEmpty} body={t.queueEmptyBody} />
      )}

      {queueReady && sortedQueue.length > 0 && (
        <ul className="mt-2" data-testid="queue-list">
          {sortedQueue.map((item) => (
            <li
              key={item.pre_summary_id}
              data-testid="queue-item"
              className="flex flex-col gap-3 min-[720px]:flex-row min-[720px]:items-center min-[720px]:justify-between border-t border-hairline-soft py-3 first:border-t-0 first:pt-0 last:pb-0"
            >
              <div className="min-w-0 flex-1 space-y-1">
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className="text-sm font-medium text-txt"
                      data-testid="queue-item-title"
                    >
                      {item.patient_name ?? t.patientFallback}
                    </span>
                    {item.patient_age != null && (
                      <span
                        className="text-xs text-txt-muted"
                        data-testid="queue-item-age"
                      >
                        {t.patientAge(item.patient_age)}
                      </span>
                    )}
                    {item.low_confidence && (
                      <span
                        data-testid="queue-item-verify"
                        className="inline-flex items-center rounded-full bg-warn-soft px-2 py-0.5 text-xs font-medium text-warn-text"
                      >
                        {t.verifyChip}
                      </span>
                    )}
                    <span
                      data-testid="queue-item-sections"
                      className="inline-flex items-center rounded-full bg-accent-soft px-2 py-0.5 text-xs font-medium text-accent-strong"
                    >
                      {t.sectionsCount(item.section_count)}
                    </span>
                  </div>
                  {item.snippet != null && item.snippet.length > 0 && (
                    <p
                      data-testid="queue-item-snippet"
                      className="line-clamp-2 text-xs text-txt-muted"
                    >
                      {item.snippet}
                    </p>
                  )}
                  <div className="flex flex-wrap items-center gap-3 text-xs text-txt-muted">
                    <span data-testid="queue-item-intake">
                      {t.queueItemMeta(item.intake_id)}
                    </span>
                    <span data-testid="queue-item-confidence">
                      {t.confidenceLabel}:{" "}
                      {confidenceDisplay(item.structuring_confidence, t)}
                    </span>
                    <span data-testid="queue-item-waiting">
                      {t.waitingFor(waitingSince(item.created_at))}
                    </span>
                  </div>
                </div>
                <Link
                  href={`/doctor/review/${item.intake_id}`}
                  data-testid="queue-item-review"
                  className="inline-flex shrink-0 items-center justify-center w-full rounded-md border border-hairline bg-surface px-3 py-1.5 text-xs font-medium text-txt-sub transition-colors hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong min-[720px]:w-auto"
                >
                  {t.reviewAction}
                </Link>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function OpenCasesCard({
  cases,
  loadStatus,
}: {
  cases: DoctorCaseRow[];
  loadStatus: LoadStatus;
}) {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorConsole;

  const casesEmpty = loadStatus === "ready" && cases.length === 0;

  return (
    <section
      className="mt-6 rounded-lg border border-hairline bg-surface p-4"
      data-testid="open-cases"
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className="text-[1.05rem] font-semibold text-txt">
          {t.casesHeading}
        </h2>
        {loadStatus === "ready" && cases.length > 0 && (
          <span
            data-testid="cases-count"
            className="inline-flex items-center rounded-full bg-accent-soft px-2 py-0.5 text-xs font-medium text-accent-strong"
          >
            {cases.length}
          </span>
        )}
      </div>

      {loadStatus === "loading" && <LoadingSkeleton />}

      {casesEmpty && (
        <EmptyState title={t.casesEmpty} body={t.casesEmptyBody} />
      )}

      {loadStatus === "ready" && cases.length > 0 && (
        // #676: the open-cases section renders the same case card the cases
        // index uses (DoctorCaseCard -> the shared DoctorListCard), so the two
        // surfaces cannot diverge - patient name plus age, verify chip on a
        // forced review, the citable case id + relative time meta line, and
        // one whole-card overlay link per card (US-66/67). Same single-column-
        // below-lg grid.
        <ul
          className="mt-2 grid grid-cols-1 items-stretch gap-4 lg:grid-cols-2"
          data-testid="cases-list"
        >
          {cases.map((c) => (
            <li key={c.case_id} data-testid="case-item" className="min-w-0">
              <DoctorCaseCard row={c} t={t} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ---- main page ----

export default function DoctorDashboardPage() {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorConsole;

  const [queue, setQueue] = useState<ReviewQueueItem[]>([]);
  const [cases, setCases] = useState<DoctorCaseRow[]>([]);
  const [loadStatus, setLoadStatus] = useState<LoadStatus>("loading");
  const [errorTraceId, setErrorTraceId] = useState<string | undefined>();
  const [bannerOpen, setBannerOpen] = useState(false);

  // Fee summary state - isolated from the console feeds
  const [profile, setProfile] = useState<DoctorProfileView | null>(null);
  const [feeLoadStatus, setFeeLoadStatus] = useState<LoadStatus>("loading");

  const load = useCallback(() => {
    setLoadStatus("loading");
    setBannerOpen(false);
    Promise.all([fetchReviewQueue(), listDoctorCases()])
      .then(([q, c]) => {
        setQueue(q);
        setCases(c.items);
        setLoadStatus("ready");
      })
      .catch((err: unknown) => {
        setErrorTraceId(err instanceof ApiError ? err.traceId : undefined);
        setLoadStatus("error");
        setBannerOpen(true);
      });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Isolated profile read - does not affect console load status. The full
  // projection is kept (not just the fee) so the getting-started checklist can
  // read the same verified/fee/about/clinic-name fields the profile-status
  // card uses, from the one request (#674).
  useEffect(() => {
    setFeeLoadStatus("loading");
    fetchDoctorProfile()
      .then((fetched: DoctorProfileView) => {
        setProfile(fetched);
        setFeeLoadStatus("ready");
      })
      .catch(() => {
        setFeeLoadStatus("error");
      });
  }, []);

  const sortedQueue = useMemo(() => sortQueue(queue), [queue]);

  // #674: the checklist's presence is driven by an empty console - no open
  // cases and an empty review queue. The step states read the profile read
  // below, so it waits for that projection (whose failures the fee card
  // already surfaces): without it the card could not truthfully mark a single
  // step done or pending.
  const showChecklist =
    loadStatus === "ready" &&
    sortedQueue.length === 0 &&
    cases.length === 0 &&
    profile !== null;

  // ---- render ----

  return (
    <>
      <GreetingHeader profile={profile} />

      {loadStatus === "error" && bannerOpen && (
        <ErrorBanner
          message={t.loadFailed}
          traceId={errorTraceId}
          onRetry={load}
          onDismiss={() => setBannerOpen(false)}
        />
      )}

      <EntryCards />

      {profile !== null && <ProfileStatusCard profile={profile} />}

      {feeLoadStatus === "loading" ? (
        <FeeSummarySkeleton />
      ) : feeLoadStatus === "error" ? (
        <FeeSummaryError
          onRetry={() => {
            setFeeLoadStatus("loading");
            fetchDoctorProfile()
              .then((fetched: DoctorProfileView) => {
                setProfile(fetched);
                setFeeLoadStatus("ready");
              })
              .catch(() => setFeeLoadStatus("error"));
          }}
        />
      ) : (
        <FeeSummaryCard feePaise={profile?.consultation_fee ?? null} />
      )}

      {showChecklist && <GettingStartedChecklist profile={profile} />}

      <ReviewQueueCard
        queue={queue}
        sortedQueue={sortedQueue}
        loadStatus={loadStatus}
      />

      <OpenCasesCard cases={cases} loadStatus={loadStatus} />
    </>
  );
}
