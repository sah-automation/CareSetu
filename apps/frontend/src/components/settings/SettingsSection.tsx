"use client";

// #797: one card of the admin Settings shell. The four sections - AI,
// notifications, feature flags and users - share this frame so a later ticket
// fills a section's body without restating the shell around it.

import type { ReactNode } from "react";

interface SettingsSectionProps {
  testId: string;
  title: string;
  description?: string;
  children: ReactNode;
}

export function SettingsSection({
  testId,
  title,
  description,
  children,
}: SettingsSectionProps) {
  return (
    <section
      data-testid={testId}
      className="rounded-lg border border-hairline bg-surface p-4"
    >
      <h2
        className="text-sm font-semibold text-txt"
        data-testid={`${testId}-title`}
      >
        {title}
      </h2>
      {description && (
        <p className="mt-0.5 text-xs text-txt-muted">{description}</p>
      )}
      <div className="mt-3">{children}</div>
    </section>
  );
}
