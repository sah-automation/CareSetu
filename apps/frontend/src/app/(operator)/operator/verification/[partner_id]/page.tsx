"use client";

// PHASE-5 T6 (#285): Operator verification detail + decision page.
// Shows partner profile, credential artifacts, verification history, and
// audit events from GET /v1/partner/verification/{id}. Approve submits
// { approve: true }, reject requires a reason then submits
// { approve: false, reason }. After decision, navigates back to queue.

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { PageHeader } from "@/components/layout/PageHeader";
import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { ApiError } from "@/lib/api-errors";
import { cn } from "@/lib/utils";
import {
  fetchVerificationDetail,
  submitOperatorDecision,
  type PartnerVerificationDetail,
  type CredentialDetail,
  type VerificationRound,
  type AuditEventDetail,
} from "@/lib/operator/api";
import { STATUS_BADGE, TYPE_BADGE, statusKey } from "@/lib/operator/badges";

type LoadStatus = "loading" | "ready" | "error";

const CREDENTIAL_STATUS: Record<string, { label: string; cls: string }> = {
  verified: { label: "Verified", cls: "bg-success-soft text-success-text" },
  pending: { label: "Pending", cls: "bg-warn-soft text-warn-text" },
  expired: { label: "Expired", cls: "bg-danger-soft text-danger" },
};

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function credentialStatus(c: CredentialDetail): {
  label: string;
  cls: string;
} {
  if (c.verified) return CREDENTIAL_STATUS.verified;
  if (c.expires_at && new Date(c.expires_at) < new Date())
    return CREDENTIAL_STATUS.expired;
  return CREDENTIAL_STATUS.pending;
}

function PartnerProfileCard({ detail }: { detail: PartnerVerificationDetail }) {
  const rows = [
    { label: "Business name", value: detail.practice_name || "N/A" },
    {
      label: "Type",
      badge:
        detail.partner_type.charAt(0).toUpperCase() +
        detail.partner_type.slice(1),
      badgeCls:
        TYPE_BADGE[detail.partner_type] ?? "bg-hairline-soft text-txt-muted",
    },
    { label: "Address", value: detail.practice_address },
    {
      label: "Service area",
      value: detail.service_area_id ? `Area #${detail.service_area_id}` : "N/A",
    },
    { label: "Submitted", value: formatDate(detail.created_at) },
  ];

  return (
    <div
      className="rounded-lg border border-hairline bg-surface p-4"
      data-testid="partner-profile"
    >
      <h2 className="mb-3 text-base font-semibold text-txt">
        Business identity
      </h2>
      <dl className="space-y-2">
        {rows.map((row) => (
          <div
            key={row.label}
            className="flex items-baseline justify-between gap-3"
          >
            <dt className="text-sm text-txt-muted">{row.label}</dt>
            <dd className="text-right text-sm font-medium text-txt">
              {"badge" in row && row.badge ? (
                <span
                  className={cn(
                    "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
                    row.badgeCls,
                  )}
                >
                  {row.badge}
                </span>
              ) : (
                "value" in row && row.value
              )}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function CredentialCard({ cred }: { cred: CredentialDetail }) {
  const status = credentialStatus(cred);
  const artifactEntries = Object.entries(cred.artifact_refs);

  return (
    <div
      className="rounded-lg border border-hairline bg-surface px-4 py-3"
      data-testid={`credential-${cred.credential_id}`}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium text-txt">{cred.credential_type}</p>
          {cred.expires_at && (
            <p className="mt-0.5 text-xs text-txt-muted">
              Expires {formatDate(cred.expires_at)}
            </p>
          )}
        </div>
        <span
          className={cn(
            "shrink-0 rounded-full px-2 py-0.5 text-xs font-medium",
            status.cls,
          )}
        >
          {status.label}
        </span>
      </div>
      {artifactEntries.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-2">
          {artifactEntries.map(([key, url]) => (
            <a
              key={key}
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center rounded-md border border-hairline bg-hairline-soft px-2 py-0.5 text-xs font-medium text-txt-sub transition-colors hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong"
            >
              {key}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

function VerificationHistoryTable({ rounds }: { rounds: VerificationRound[] }) {
  if (rounds.length === 0) return null;

  return (
    <div
      className="rounded-lg border border-hairline bg-surface"
      data-testid="verification-history"
    >
      <h2 className="border-b border-hairline px-4 py-3 text-base font-semibold text-txt">
        Verification history
      </h2>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-hairline bg-accent-soft">
              <th className="px-4 py-2 font-medium text-txt">Round</th>
              <th className="px-4 py-2 font-medium text-txt">Status</th>
              <th className="px-4 py-2 font-medium text-txt">Decision</th>
              <th className="px-4 py-2 font-medium text-txt">Reason</th>
              <th className="px-4 py-2 font-medium text-txt">Date</th>
            </tr>
          </thead>
          <tbody>
            {rounds.map((round) => (
              <tr
                key={round.round}
                className="border-b border-hairline last:border-0"
              >
                <td className="px-4 py-2.5 text-txt">{round.round}</td>
                <td className="px-4 py-2.5">
                  <span
                    className={cn(
                      "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
                      STATUS_BADGE[statusKey(round.status)] ??
                        "bg-hairline-soft text-txt-muted",
                    )}
                  >
                    {round.status}
                  </span>
                </td>
                <td className="px-4 py-2.5 text-txt-sub">
                  {round.decision ?? "\u2014"}
                </td>
                <td className="max-w-[200px] truncate px-4 py-2.5 text-txt-sub">
                  {round.decision_reason ?? "\u2014"}
                </td>
                <td className="px-4 py-2.5 text-txt-sub">
                  {round.decided_at
                    ? formatDateTime(round.decided_at)
                    : "\u2014"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AuditTimeline({ events }: { events: AuditEventDetail[] }) {
  if (events.length === 0) return null;

  return (
    <div data-testid="audit-timeline">
      <h2 className="mb-3 text-base font-semibold text-txt">Audit trail</h2>
      <ol className="relative border-l border-hairline ml-2 space-y-4">
        {events.map((event) => (
          <li
            key={event.id}
            className="relative pl-6"
            data-testid={`audit-event-${event.id}`}
          >
            <span
              className="absolute -left-[5px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-hairline bg-surface"
              aria-hidden="true"
            />
            <p className="text-sm font-medium text-txt">{event.event_type}</p>
            <p className="mt-0.5 text-xs text-txt-muted">
              {formatDateTime(event.timestamp)}
              {event.actor_id && ` \u00b7 Actor ${event.actor_id}`}
              {event.scope && ` \u00b7 ${event.scope}`}
            </p>
            <button
              type="button"
              className="mt-0.5 font-mono text-[11px] text-txt-muted break-all text-left hover:text-accent-strong"
              title={`Full hash: ${event.hash}`}
            >
              hash: {event.hash.slice(0, 16)}...
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="space-y-4" data-testid="detail-skeleton">
      <div className="rounded-lg border border-hairline bg-surface p-4">
        <Skeleton className="mb-3 h-5 w-32" />
        <div className="space-y-2">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="flex justify-between">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-4 w-32" />
            </div>
          ))}
        </div>
      </div>
      <div className="rounded-lg border border-hairline bg-surface p-4">
        <Skeleton className="mb-3 h-5 w-40" />
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-12 w-full rounded-lg" />
          ))}
        </div>
      </div>
      <Skeleton className="h-20 w-full rounded-lg" />
    </div>
  );
}

export default function VerificationDetailPage() {
  const params = useParams<{ partner_id: string }>();
  const router = useRouter();
  const partnerId = Number(params.partner_id);

  const [detail, setDetail] = useState<PartnerVerificationDetail | null>(null);
  const [status, setStatus] = useState<LoadStatus>("loading");
  const [errorTraceId, setErrorTraceId] = useState<string | undefined>(
    undefined,
  );
  const [bannerOpen, setBannerOpen] = useState(false);

  const [approveOpen, setApproveOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [decisionTraceId, setDecisionTraceId] = useState<string | undefined>(
    undefined,
  );

  const load = useCallback(() => {
    setStatus("loading");
    setBannerOpen(false);
    fetchVerificationDetail(partnerId)
      .then((data) => {
        setDetail(data);
        setStatus("ready");
      })
      .catch((error: unknown) => {
        setErrorTraceId(error instanceof ApiError ? error.traceId : undefined);
        setStatus("error");
        setBannerOpen(true);
      });
  }, [partnerId]);

  useEffect(() => {
    load();
  }, [load]);

  const handleApprove = useCallback(async () => {
    setSubmitting(true);
    setDecisionError(null);
    setDecisionTraceId(undefined);
    try {
      await submitOperatorDecision(partnerId, { approve: true });
      router.push("/operator");
    } catch (error: unknown) {
      setSubmitting(false);
      setApproveOpen(false);
      setDecisionError(
        error instanceof ApiError
          ? error.message
          : error instanceof Error
            ? error.message
            : "Could not submit the decision.",
      );
      setDecisionTraceId(error instanceof ApiError ? error.traceId : undefined);
    }
  }, [partnerId, router]);

  const handleReject = useCallback(async () => {
    if (!rejectReason.trim()) return;
    setSubmitting(true);
    setDecisionError(null);
    setDecisionTraceId(undefined);
    try {
      await submitOperatorDecision(partnerId, {
        approve: false,
        reason: rejectReason.trim(),
      });
      router.push("/operator");
    } catch (error: unknown) {
      setSubmitting(false);
      setRejectOpen(false);
      setDecisionError(
        error instanceof ApiError
          ? error.message
          : error instanceof Error
            ? error.message
            : "Could not submit the decision.",
      );
      setDecisionTraceId(error instanceof ApiError ? error.traceId : undefined);
    }
  }, [partnerId, rejectReason, router]);

  const pageName =
    detail?.practice_name || (detail ? `Partner #${detail.partner_id}` : "");

  return (
    <>
      <PageHeader
        title="Verification detail"
        description="Review the submission and decide. Approved partners are activated."
        breadcrumbs={[
          { label: "Home", href: "/operator" },
          { label: "Verifications", href: "/operator" },
          { label: pageName || "Loading..." },
        ]}
      />

      {status === "error" && bannerOpen && (
        <ErrorBanner
          message="Could not load the verification detail."
          traceId={errorTraceId}
          onRetry={load}
          onDismiss={() => setBannerOpen(false)}
        />
      )}

      {decisionError && (
        <ErrorBanner
          message={decisionError}
          traceId={decisionTraceId}
          onDismiss={() => {
            setDecisionError(null);
            setDecisionTraceId(undefined);
          }}
        />
      )}

      {status === "loading" && <LoadingSkeleton />}

      {status === "ready" && detail && (
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2">
            <PartnerProfileCard detail={detail} />
            <div
              className="rounded-lg border border-hairline bg-surface p-4"
              data-testid="credentials-card"
            >
              <h2 className="mb-3 text-base font-semibold text-txt">
                Uploaded credentials
              </h2>
              {detail.credentials.length === 0 ? (
                <p className="text-sm text-txt-muted">
                  No credentials uploaded.
                </p>
              ) : (
                <div className="space-y-2">
                  {detail.credentials.map((cred) => (
                    <CredentialCard key={cred.credential_id} cred={cred} />
                  ))}
                </div>
              )}
            </div>
          </div>

          <VerificationHistoryTable rounds={detail.verification_history} />

          <AuditTimeline events={detail.audit_events} />

          <div
            className="rounded-lg border border-hairline bg-surface p-4"
            data-testid="decision-actions"
          >
            <h2 className="mb-2 text-base font-semibold text-txt">Decision</h2>
            <p className="mb-4 text-sm text-txt-muted">
              Approved partners receive the{" "}
              <code className="rounded bg-hairline-soft px-1 py-0.5 text-xs">
                partner.activated
              </code>{" "}
              event. Rejection records the reason for the applicant&apos;s
              resubmission.
            </p>
            <div className="flex flex-wrap gap-3">
              <Button
                size="lg"
                onClick={() => setApproveOpen(true)}
                data-testid="btn-approve"
              >
                Approve
              </Button>
              <Button
                size="lg"
                variant="destructive"
                onClick={() => {
                  setRejectReason("");
                  setRejectOpen(true);
                }}
                data-testid="btn-reject"
              >
                Reject with reason
              </Button>
            </div>
          </div>
        </div>
      )}

      <Sheet open={approveOpen} onOpenChange={setApproveOpen}>
        <SheetContent side="bottom" className="sm:max-w-lg">
          <SheetHeader>
            <SheetTitle>Confirm approval</SheetTitle>
            <SheetDescription>
              {detail?.practice_name || "This partner"} will be activated and
              indexed for directory search.
            </SheetDescription>
          </SheetHeader>
          <div className="mt-4 flex gap-3">
            <Button
              className="flex-1"
              loading={submitting}
              onClick={handleApprove}
              data-testid="confirm-approve"
            >
              Confirm approve
            </Button>
            <Button
              variant="outline"
              onClick={() => setApproveOpen(false)}
              disabled={submitting}
            >
              Cancel
            </Button>
          </div>
        </SheetContent>
      </Sheet>

      <Sheet open={rejectOpen} onOpenChange={setRejectOpen}>
        <SheetContent side="bottom" className="sm:max-w-lg">
          <SheetHeader>
            <SheetTitle>Reject application</SheetTitle>
            <SheetDescription>
              The rejection reason is recorded on the partner&apos;s application
              and they can resubmit with corrected credentials.
            </SheetDescription>
          </SheetHeader>
          <div className="mt-4">
            <label
              htmlFor="reject-reason"
              className="mb-1 block text-sm font-medium text-txt"
            >
              Reason shown to the applicant
            </label>
            <textarea
              id="reject-reason"
              className="w-full rounded-md border border-hairline bg-surface px-3 py-2 text-sm text-txt placeholder:text-txt-muted focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
              rows={4}
              placeholder="Be specific - this text appears on their rejected screen."
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              data-testid="reject-reason-input"
            />
            <p className="mt-1 text-xs text-txt-muted">
              Required. Example: &quot;The document photo is blurry - please
              re-upload a clear image.&quot;
            </p>
          </div>
          <div className="mt-4 flex gap-3">
            <Button
              variant="destructive"
              className="flex-1"
              loading={submitting}
              disabled={!rejectReason.trim()}
              onClick={handleReject}
              data-testid="confirm-reject"
            >
              Confirm rejection
            </Button>
            <Button
              variant="outline"
              onClick={() => setRejectOpen(false)}
              disabled={submitting}
            >
              Cancel
            </Button>
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
}
