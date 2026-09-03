"use client";

// PHASE-5 T5 (#284): Operator verification queue list - fetches
// GET /v1/partner/verification-queue, renders a table of Under Verification
// submissions with partner identity, type, registration age, and status badge.
// Sortable by registration age (default: oldest first, KPI-004 scenario 2),
// partner_type, and status. Click-through to detail view at
// /operator/verification/[id]. Loading skeleton and error banner follow the
// record/page.tsx pattern (blueprint section 9.1).

import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowUpDown } from "lucide-react";

import { PageHeader } from "@/components/layout/PageHeader";
import { EmptyState } from "@/components/layout/EmptyState";
import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api-errors";
import { cn } from "@/lib/utils";
import {
  fetchVerificationQueue,
  type PartnerQueueItem,
  type PartnerQueue,
} from "@/lib/operator/api";

type LoadStatus = "loading" | "ready" | "error";

type SortField = "registration_age" | "partner_type" | "status";

interface SortConfig {
  field: SortField;
  label: string;
}

const SORT_OPTIONS: SortConfig[] = [
  { field: "registration_age", label: "Waiting time" },
  { field: "partner_type", label: "Type" },
  { field: "status", label: "Status" },
];

const TYPE_BADGE: Record<string, string> = {
  doctor: "bg-accent-soft text-accent-strong",
  lab: "bg-success-soft text-success-text",
  chemist: "bg-warm-soft text-txt-sub",
};

const STATUS_BADGE: Record<string, string> = {
  "Under Verification": "bg-warn-soft text-warn-text",
  verified: "bg-success-soft text-success-text",
  rejected: "bg-danger-soft text-danger",
};

function registrationAge(createdAt: string): string {
  const ms = Date.now() - new Date(createdAt).getTime();
  const hours = Math.floor(ms / 3_600_000);
  if (hours < 1) return "< 1h";
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  return days === 1 ? "1 day" : `${days} days`;
}

function sortItems(
  items: PartnerQueueItem[],
  field: SortField,
): PartnerQueueItem[] {
  const sorted = [...items];
  if (field === "registration_age") {
    sorted.sort(
      (a, b) =>
        new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
    );
  } else if (field === "partner_type") {
    sorted.sort((a, b) => a.partner_type.localeCompare(b.partner_type));
  } else {
    sorted.sort((a, b) => a.status.localeCompare(b.status));
  }
  return sorted;
}

function LoadingSkeleton() {
  return (
    <div className="space-y-3" data-testid="queue-skeleton">
      {Array.from({ length: 5 }).map((_, i) => (
        <div
          key={i}
          className="flex items-center gap-4 rounded-lg border border-hairline bg-surface p-4"
        >
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-5 w-16 rounded-full" />
          <Skeleton className="h-4 w-12" />
          <Skeleton className="h-5 w-20 rounded-full" />
          <Skeleton className="h-8 w-20 rounded-md" />
        </div>
      ))}
    </div>
  );
}

export default function OperatorDashboardPage() {
  const [queue, setQueue] = useState<PartnerQueue | null>(null);
  const [status, setStatus] = useState<LoadStatus>("loading");
  const [errorTraceId, setErrorTraceId] = useState<string | undefined>(
    undefined,
  );
  const [bannerOpen, setBannerOpen] = useState(false);
  const [sortField, setSortField] = useState<SortField>("registration_age");

  const load = useCallback(() => {
    setStatus("loading");
    fetchVerificationQueue({
      status: "Under Verification",
      sort_by: "registration_age",
    })
      .then((data) => {
        setQueue(data);
        setStatus("ready");
        setBannerOpen(false);
      })
      .catch((error: unknown) => {
        setErrorTraceId(error instanceof ApiError ? error.traceId : undefined);
        setStatus("error");
        setBannerOpen(true);
      });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const items = useMemo(() => {
    if (!queue) return [];
    return sortItems(queue.items, sortField);
  }, [queue, sortField]);

  return (
    <>
      <PageHeader
        title="Verification queue"
        description="Under Verification partners, oldest-first."
      />

      {status === "error" && bannerOpen && (
        <ErrorBanner
          message="Could not load the verification queue."
          traceId={errorTraceId}
          onRetry={load}
          onDismiss={() => setBannerOpen(false)}
        />
      )}

      {status === "loading" && <LoadingSkeleton />}

      {status === "ready" && items.length === 0 && (
        <EmptyState
          title="No pending verifications"
          body="All partner submissions have been reviewed."
        />
      )}

      {status === "ready" && items.length > 0 && (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <span className="text-sm text-txt-muted">Sort by:</span>
            {SORT_OPTIONS.map((opt) => (
              <button
                key={opt.field}
                type="button"
                onClick={() => setSortField(opt.field)}
                className={cn(
                  "inline-flex items-center gap-1 rounded-full border px-3 py-1 text-sm font-medium transition-colors",
                  sortField === opt.field
                    ? "border-accent bg-accent text-on-accent"
                    : "border-hairline bg-surface text-txt-sub hover:border-accent-border hover:bg-accent-soft",
                )}
                data-testid={`sort-${opt.field}`}
              >
                {opt.label}
                {sortField === opt.field && (
                  <ArrowUpDown size={12} aria-hidden="true" />
                )}
              </button>
            ))}
          </div>

          <div className="overflow-x-auto rounded-lg border border-hairline">
            <table
              className="w-full text-left text-sm"
              data-testid="queue-table"
            >
              <thead>
                <tr className="border-b border-hairline bg-accent-soft">
                  <th className="px-4 py-2.5 font-medium text-txt">
                    Applicant
                  </th>
                  <th className="px-4 py-2.5 font-medium text-txt">Type</th>
                  <th className="px-4 py-2.5 font-medium text-txt">Status</th>
                  <th className="px-4 py-2.5 font-medium text-txt">Waiting</th>
                  <th className="px-4 py-2.5 font-medium text-txt">Round</th>
                  <th className="px-4 py-2.5 font-medium text-txt" />
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr
                    key={item.partner_id}
                    className="border-b border-hairline last:border-0 hover:bg-accent-soft/50"
                    data-testid={`queue-item-${item.partner_id}`}
                  >
                    <td className="px-4 py-3">
                      <p className="font-medium text-txt">
                        {item.practice_name || `Partner #${item.partner_id}`}
                      </p>
                      <p className="mt-0.5 text-xs text-txt-muted">
                        {item.practice_address}
                      </p>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={cn(
                          "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
                          TYPE_BADGE[item.partner_type] ??
                            "bg-hairline-soft text-txt-muted",
                        )}
                      >
                        {item.partner_type.charAt(0).toUpperCase() +
                          item.partner_type.slice(1)}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={cn(
                          "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
                          STATUS_BADGE[item.status] ??
                            "bg-hairline-soft text-txt-muted",
                        )}
                      >
                        {item.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-txt-sub">
                      {registrationAge(item.created_at)}
                    </td>
                    <td className="px-4 py-3 text-sm text-txt-sub">
                      {item.round}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <a
                        href={`/operator/verification/${item.partner_id}`}
                        className="inline-flex items-center rounded-md border border-hairline bg-surface px-3 py-1.5 text-xs font-medium text-txt-sub transition-colors hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong"
                      >
                        Review
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}
