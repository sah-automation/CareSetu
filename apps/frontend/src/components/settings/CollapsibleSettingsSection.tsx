"use client";

import { useEffect, useState } from "react";

import { SettingsSection } from "./SettingsSection";

interface CollapsibleSettingsSectionProps {
  sectionKey: string;
  title: string;
  description?: string;
  testId?: string;
  children: React.ReactNode;
}

const storageKeyFor = (sectionKey: string) =>
  `caresetu.settings.collapse.${sectionKey}`;

export function CollapsibleSettingsSection({
  sectionKey,
  title,
  description,
  testId,
  children,
}: CollapsibleSettingsSectionProps) {
  const resolvedTestId = testId ?? `settings-${sectionKey}`;

  const [collapsed, setCollapsed] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    try {
      return (
        window.sessionStorage.getItem(storageKeyFor(sectionKey)) === "true"
      );
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      window.sessionStorage.setItem(
        storageKeyFor(sectionKey),
        String(collapsed),
      );
    } catch {
      // ignore storage errors
    }
  }, [sectionKey, collapsed]);

  function toggle() {
    setCollapsed((current) => !current);
  }

  return (
    <SettingsSection
      testId={resolvedTestId}
      title={title}
      description={description}
    >
      <div data-testid={`${resolvedTestId}-collapsible`}>
        <button
          type="button"
          onClick={toggle}
          aria-expanded={!collapsed}
          aria-controls={`${resolvedTestId}-body`}
          className="mb-2 inline-flex items-center gap-1 text-xs font-medium text-txt-sub hover:text-txt"
          data-testid={`${resolvedTestId}-toggle`}
        >
          <span data-testid={`${resolvedTestId}-title-state`}>
            {collapsed ? "Expand" : "Collapse"}
          </span>
        </button>
        {!collapsed && <div id={`${resolvedTestId}-body`}>{children}</div>}
      </div>
    </SettingsSection>
  );
}
