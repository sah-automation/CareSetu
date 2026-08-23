"use client";

// PHASE-2.6 T08 (#199): the chassis block opening every logged-in app page
// (blueprint §2.5, finalized PROTO-PHASE-2.6 view shell-full.html):
//   H1 title · optional one-line description · primary action right-aligned,
//   sitting directly under the top bar inside the content padding.
// Breadcrumbs render only when the caller passes them (depth 2+ pages);
// home/root pages pass none and get no breadcrumb nav at all.

import Link from "next/link";
import type { ReactNode } from "react";

export interface Crumb {
  label: string;
  href?: string;
}

// Depth 2+ only (§2.5): mirrors URL structure; the last crumb is plain text,
// never a link; on mobile the trail collapses to a single back-link labeled
// with the parent section name.
export function Breadcrumbs({ items }: { items: Crumb[] }) {
  if (items.length < 2) {
    return null;
  }
  const parent = items[items.length - 2];
  const last = items[items.length - 1];

  return (
    <nav aria-label="Breadcrumb" data-testid="breadcrumbs">
      {/* Mobile: single back-link to the parent section */}
      <Link
        href={parent.href ?? "#"}
        className="text-sm font-medium text-accent-strong hover:underline lg:hidden"
        data-testid="breadcrumb-back"
      >
        &larr; {parent.label}
      </Link>
      {/* Desktop: full trail */}
      <ol
        className="hidden items-center gap-1.5 text-sm text-txt-muted lg:flex"
        data-testid="breadcrumb-trail"
      >
        {items.slice(0, -1).map((crumb, index) => (
          <li key={index} className="flex items-center gap-1.5">
            {crumb.href ? (
              <Link
                href={crumb.href}
                className="hover:text-accent-strong hover:underline"
              >
                {crumb.label}
              </Link>
            ) : (
              <span>{crumb.label}</span>
            )}
            <span aria-hidden="true" className="text-txt-muted">
              /
            </span>
          </li>
        ))}
        <li>
          <span aria-current="page" data-testid="breadcrumb-current">
            {last.label}
          </span>
        </li>
      </ol>
    </nav>
  );
}

interface PageHeaderProps {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  breadcrumbs?: Crumb[];
}

export function PageHeader({
  title,
  description,
  action,
  breadcrumbs,
}: PageHeaderProps) {
  return (
    <div className="mb-6" data-testid="page-header">
      {breadcrumbs && <Breadcrumbs items={breadcrumbs} />}
      <div className="mt-2 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold text-txt">{title}</h1>
          {description && (
            <p className="mt-1 text-sm text-txt-muted">{description}</p>
          )}
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </div>
    </div>
  );
}
