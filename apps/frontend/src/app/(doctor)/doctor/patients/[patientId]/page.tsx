"use client";

// PHASE-8.1 (#541): doctor console per-patient detail (US-15..US-19). The
// page reads one patient through the gated detail API (#540) and renders each
// block - contact/photo, consultation history, health background - exactly as
// the backend answers it: a live grant opens the section, a denied section
// comes back null and renders as a calm locked "not shared" state, never an
// error. The case workspace deep link points at the doctor's own case
// (cases/[caseId]). Every client read on this page goes through the gated
// detail + photo APIs - no client-side permission logic is invented. All copy
// bilingual en/hi (REQ-006).

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ApiError } from "@/lib/api-errors";
import {
  fetchDoctorPatientDetail,
  fetchDoctorPatientPhoto,
  type DoctorPatientDetailView,
  type RecordScope,
} from "@/lib/doctor/api";
import { STRINGS, type Dictionary } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { cn } from "@/lib/utils";
import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Skeleton } from "@/components/ui/skeleton";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { NotSharedCard } from "@/components/doctor/NotSharedCard";
// #679 (parent #673): the read-only health-background block now lives in a
// shared presentational component so the case workspace History tab (#682) can
// render the same facts. CHIP_TONE is the accent chip tone the header band and
// the health background share - the same soft-accent pill the scope badges and
// the shared doctor card render, so every read-only chip on the doctor surface
// looks like one family.
import {
  CHIP_TONE,
  HealthBackgroundBlock,
} from "@/components/doctor/HealthBackgroundBlock";
// #680 (parent #673): the consultation history renders each entry through the
// shared record-entry renderer (#677) so the patient profile and the case
// workspace History tab show identical content (US-33). The custom test id
// keeps the existing `consultation-entry` hook and its `-type` derived id,
// while the renderer adds `-detail`/`-medicine` for the per-type facts.
import { RecordEntryItem } from "@/components/record/RecordEntryItem";

type LoadStatus = "loading" | "ready" | "error";

function stageLabel(stage: string, t: Dictionary["doctorConsole"]): string {
  switch (stage) {
    case "pre_summary":
      return t.stagePreSummary;
    case "prescription_pending":
      return t.stagePrescriptionPending;
    case "closed":
      return t.stageClosed;
    default:
      return stage;
  }
}

function scopeBadges(scopes: RecordScope[], t: Dictionary["doctorPatients"]) {
  return scopes.map((scope) => (
    <span
      key={scope}
      data-testid={`detail-scope-${scope}`}
      className="inline-flex items-center rounded-full bg-accent-soft px-2 py-0.5 text-xs font-medium text-accent-strong"
    >
      {t.scopeBadge[scope]}
    </span>
  ));
}

function SectionHeading({ title }: { title: string }) {
  return (
    <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-txt-muted">
      {title}
    </h2>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="sm:flex sm:items-center sm:justify-between sm:gap-3">
      <dt className="text-xs font-medium uppercase tracking-wide text-txt-muted">
        {label}
      </dt>
      <dd className="text-sm text-txt" data-testid="detail-field-value">
        {value}
      </dd>
    </div>
  );
}

interface Lookup {
  t: Dictionary["doctorPatients"];
  consoleT: Dictionary["doctorConsole"];
  recordT: Dictionary["record"];
  lang: "en" | "hi";
  /** Shared bilingual gender vocabulary, resolved once where lookup is built. */
  genders: Record<string, string>;
}

function ContactBlock({
  detail,
  photoUrl,
  lookup,
}: {
  detail: DoctorPatientDetailView;
  photoUrl: string | null;
  lookup: Lookup;
}) {
  const { t, consoleT, genders } = lookup;
  const contact = detail.contact;
  if (contact == null) {
    return <NotSharedCard title={t.notSharedTitle} body={t.notSharedBody} />;
  }
  // #659 (US-56/57): the header reads as one band - large avatar and name
  // lead, age and gender follow as inline chips rather than stacked form
  // rows. The gender enum renders through the shared bilingual vocabulary so
  // the chip ships in both locales; an unrecognised value falls back to the
  // raw token rather than silently vanishing.
  const ageText = contact.age != null ? String(contact.age) : t.notRecorded;
  const genderText =
    contact.gender != null
      ? genders[contact.gender] ?? contact.gender
      : t.notRecorded;
  return (
    <div className="rounded-lg border border-hairline bg-surface p-4">
      <div
        className="flex items-center gap-4"
        data-testid="patient-header-band"
      >
        {photoUrl ? (
          <img
            src={photoUrl}
            alt={t.photoAlt(contact.name ?? consoleT.patientFallback)}
            data-testid="patient-photo"
            className="h-20 w-20 shrink-0 rounded-full object-cover"
          />
        ) : (
          <Avatar
            name={contact.name}
            className="h-20 w-20 shrink-0 bg-accent-soft text-2xl font-semibold text-accent-strong"
            data-testid="patient-photo-fallback"
          />
        )}
        <div className="min-w-0">
          <p
            className="text-lg font-semibold break-words text-txt"
            data-testid="patient-detail-name"
          >
            {contact.name ?? t.notRecorded}
          </p>
          <div
            className="mt-2 flex flex-wrap items-center gap-1.5"
            data-testid="patient-header-chips"
          >
            <Badge data-testid="patient-age-chip" className={CHIP_TONE}>
              {`${t.ageLabel}: ${ageText}`}
            </Badge>
            <Badge data-testid="patient-gender-chip" className={CHIP_TONE}>
              {`${t.genderLabel}: ${genderText}`}
            </Badge>
          </div>
        </div>
      </div>
      <dl className="mt-4 space-y-2">
        <Field label={t.areaLabel} value={contact.area ?? t.notRecorded} />
        <Field
          label={t.emergencyContactLabel}
          value={contact.emergency_contact ?? t.notRecorded}
        />
      </dl>
    </div>
  );
}

function ConsultationHistoryBlock({
  detail,
  lookup,
}: {
  detail: DoctorPatientDetailView;
  lookup: Lookup;
}) {
  const { t, recordT, lang } = lookup;
  const history = detail.consultation_history;
  if (history == null) {
    return <NotSharedCard title={t.notSharedTitle} body={t.notSharedBody} />;
  }
  if (history.entries.length === 0) {
    return (
      <div
        data-testid="consultation-empty"
        className="rounded-lg border border-hairline bg-surface px-4 py-4 text-sm text-txt-muted"
      >
        {t.consultationHistoryEmpty}
      </div>
    );
  }
  return (
    <ul data-testid="consultation-list" className="space-y-2">
      {history.entries.map((entry, index) => (
        <RecordEntryItem
          key={entry.entry_id ?? index}
          entry={entry}
          labels={recordT}
          lang={lang}
          testId="consultation-entry"
        />
      ))}
    </ul>
  );
}

function CaseWorkspaceBlock({
  detail,
  lookup,
}: {
  detail: DoctorPatientDetailView;
  lookup: Lookup;
}) {
  const { t, consoleT } = lookup;
  const link = detail.case_workspace;
  if (link == null) {
    return (
      <p
        data-testid="case-workspace-none"
        className="rounded-lg border border-hairline bg-surface px-4 py-4 text-sm text-txt-muted"
      >
        {t.noCaseStage}
      </p>
    );
  }
  return (
    <div
      data-testid="case-workspace-present"
      className="flex items-center justify-between gap-3 rounded-lg border border-hairline bg-surface p-4"
    >
      <div className="min-w-0">
        <Link
          href={`/doctor/cases/${link.case_id}`}
          data-testid="case-workspace-link"
          className="inline-flex items-center rounded-md border border-hairline bg-surface px-3 py-1.5 text-xs font-medium text-txt-sub transition-colors hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong"
        >
          {t.openCaseAction}
        </Link>
      </div>
      <span
        data-testid="case-workspace-stage"
        className={cn(
          "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
          link.stage === "pre_summary"
            ? "bg-warn-soft text-warn-text"
            : "bg-accent-soft text-accent-strong",
        )}
      >
        {stageLabel(link.stage, consoleT)}
      </span>
    </div>
  );
}

function DetailSkeleton() {
  return (
    <div className="space-y-3" data-testid="patient-detail-skeleton">
      <div className="flex items-center gap-3">
        <Skeleton className="h-20 w-20 rounded-full" />
        <div className="space-y-2">
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-4 w-24" />
        </div>
      </div>
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-24 w-full" />
    </div>
  );
}

export default function DoctorPatientDetailPage() {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorPatients;
  const consoleT = STRINGS[lang].doctorConsole;
  const recordT = STRINGS[lang].record;

  const params = useParams<{ patientId: string }>();
  const patientId = Number(params.patientId);
  const invalidId = !Number.isInteger(patientId) || patientId <= 0;

  const [detail, setDetail] = useState<DoctorPatientDetailView | null>(null);
  const [loadStatus, setLoadStatus] = useState<LoadStatus>("loading");
  const [errorTraceId, setErrorTraceId] = useState<string | undefined>();
  const [bannerOpen, setBannerOpen] = useState(false);
  const [photoUrl, setPhotoUrl] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoadStatus("loading");
    setBannerOpen(false);
    fetchDoctorPatientDetail(patientId)
      .then((view) => {
        setDetail(view);
        setLoadStatus("ready");
      })
      .catch((err: unknown) => {
        setErrorTraceId(err instanceof ApiError ? err.traceId : undefined);
        setLoadStatus("error");
        setBannerOpen(true);
      });
  }, [patientId]);

  useEffect(() => {
    if (invalidId) return;
    load();
  }, [load, invalidId]);

  // The patient photo streams through the gated photo endpoint (ADR-0020):
  // fetch the bytes via the authed transport and present them as an object
  // URL. A missing or denied photo degrades to the avatar fallback, never an
  // error surface. The object URL is revoked on teardown so a stale URL is
  // never left alive after navigating away.
  //
  // `has_photo` is a boolean presence flag, not a nullable ref (S2: the console
  // never learns where the photo is stored), so "no photo" is `false` rather
  // than `null` - the fetch keys off the same flag the detail body carried.
  useEffect(() => {
    const hasPhoto = detail?.contact?.has_photo ?? false;
    if (!hasPhoto) {
      setPhotoUrl(null);
      return;
    }
    let cancelled = false;
    let objectUrl: string | null = null;
    setPhotoUrl(null);
    void fetchDoctorPatientPhoto(patientId)
      .then((blob) => {
        if (cancelled) return;
        if (typeof URL.createObjectURL !== "function") return;
        objectUrl = URL.createObjectURL(blob);
        setPhotoUrl(objectUrl);
      })
      .catch(() => {
        if (cancelled) return;
        setPhotoUrl(null);
      });
    return () => {
      cancelled = true;
      if (objectUrl != null) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [detail?.contact?.has_photo, patientId]);

  const ready = loadStatus === "ready" && detail != null;
  const lookup: Lookup = {
    t,
    consoleT,
    recordT,
    lang,
    genders: STRINGS[lang].profile.genders,
  };

  // A non-numeric route segment is a malformed URL (the app only emits
  // numeric patient ids), so bail out early instead of calling the API with a
  // NaN path param and surfacing a misleading trace-backed error.
  if (invalidId) {
    return (
      <>
        <PageHeader
          title={t.contactHeading}
          breadcrumbs={[
            { label: t.title, href: "/doctor/patients" },
            { label: t.contactHeading },
          ]}
        />
        <ErrorBanner message={t.loadFailedDetail} />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title={
          ready && detail.contact?.name ? detail.contact.name : t.contactHeading
        }
        breadcrumbs={[
          { label: t.title, href: "/doctor/patients" },
          {
            label:
              ready && detail.contact?.name
                ? detail.contact.name
                : t.contactHeading,
          },
        ]}
      />

      {loadStatus === "error" && bannerOpen && (
        <ErrorBanner
          message={t.loadFailedDetail}
          traceId={errorTraceId}
          onRetry={load}
          onDismiss={() => setBannerOpen(false)}
        />
      )}

      {loadStatus === "loading" && <DetailSkeleton />}

      {ready && (
        <>
          {detail.granted_scopes.length > 0 && (
            <div
              className="mb-6 flex flex-wrap items-center gap-1.5"
              data-testid="detail-scope-badges"
            >
              {scopeBadges(detail.granted_scopes, t)}
            </div>
          )}

          <section data-testid="detail-contact">
            <SectionHeading title={t.contactHeading} />
            <ContactBlock detail={detail} photoUrl={photoUrl} lookup={lookup} />
          </section>

          <section className="mt-6" data-testid="detail-consultation-history">
            <SectionHeading title={t.consultationHistoryHeading} />
            <ConsultationHistoryBlock detail={detail} lookup={lookup} />
          </section>

          <section className="mt-6" data-testid="detail-health-background">
            <SectionHeading title={t.healthBackgroundHeading} />
            <HealthBackgroundBlock
              healthBackground={detail.health_background}
              labels={lookup.t}
            />
          </section>

          <section className="mt-6" data-testid="detail-case-workspace">
            <SectionHeading title={t.caseWorkspaceHeading} />
            <CaseWorkspaceBlock detail={detail} lookup={lookup} />
          </section>
        </>
      )}
    </>
  );
}
