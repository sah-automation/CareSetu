"use client";

import { Fragment, useEffect, useId, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useAuth } from "@/lib/auth/AuthContext";
import { useLang } from "@/lib/i18n/LangContext";

import {
  filterNavItems,
  isNavItemActive,
  sidebarSections,
  type NavItemDef,
  type SidebarSection,
} from "./nav-config";
import { CountPill, SoonBadge } from "./NavItemLink";
import type { Role } from "./types";

const ACCORDION_SECTION_KEYS = new Set([
  "metrics",
  "reliability",
  "qualitySecurity",
  "account",
]);

export interface MoreSheetAccordionProps {
  role: Role;
  config: NavItemDef[];
  onNavigate: () => void;
}

export function OverflowRow({
  item,
  label,
  onNavigate,
}: {
  item: NavItemDef;
  label: string;
  onNavigate: () => void;
}) {
  const pathname = usePathname();
  const Icon = item.icon;
  const className =
    "flex min-h-12 w-full items-center gap-3 rounded px-2 py-2 text-sm font-medium";
  // A sheet row is a destination, so it carries the page-level marker. The
  // group row above it carries the group marker ("true"), which keeps exactly
  // one element in the sheet claiming the current page.
  const active = isNavItemActive(item, pathname);

  if (item.soon) {
    return (
      <span
        aria-disabled="true"
        className={cn(className, "cursor-not-allowed text-txt-sub opacity-60")}
        data-testid={`more-${item.key}`}
      >
        <Icon size={20} className="shrink-0" />
        <span className="flex-1">{label}</span>
        <SoonBadge />
      </span>
    );
  }

  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      data-active={active || undefined}
      className={cn(
        className,
        active
          ? "font-semibold text-accent-strong"
          : "text-txt-sub hover:bg-accent-soft hover:text-txt",
      )}
      data-testid={`more-${item.key}`}
    >
      <Icon size={20} className="shrink-0" />
      <span className="flex-1">{label}</span>
      {typeof item.count === "number" && <CountPill count={item.count} />}
    </Link>
  );
}

export function SheetGroupNavItem({
  item,
  onNavigate,
}: {
  item: NavItemDef;
  onNavigate: () => void;
}) {
  const pathname = usePathname();
  const { lang } = useLang();
  const label = STRINGS[lang].nav[item.labelKey];
  const Icon = item.icon;
  const active = isNavItemActive(item, pathname);
  const children = item.children ?? [];

  return (
    <div data-testid={`more-group-${item.key}`}>
      <Link
        href={item.href}
        onClick={onNavigate}
        aria-current={active ? "true" : undefined}
        data-active={active || undefined}
        data-testid={`more-${item.key}`}
        className={cn(
          "flex min-h-12 w-full items-center gap-3 rounded px-2 py-2 text-sm font-semibold",
          active
            ? "text-accent-strong"
            : "text-txt-sub hover:bg-accent-soft hover:text-txt",
        )}
      >
        <Icon size={20} className="shrink-0" />
        <span className="flex-1">{label}</span>
      </Link>
      <ul
        className="mt-0.5 ml-5 space-y-0.5 border-l border-hairline pl-1"
        data-testid={`more-group-${item.key}-menu`}
      >
        {children.map((child) => (
          <li key={child.key}>
            <OverflowRow
              item={child}
              label={STRINGS[lang].nav[child.labelKey]}
              onNavigate={onNavigate}
            />
          </li>
        ))}
      </ul>
    </div>
  );
}

export function MoreSheetAccordion({
  role,
  config,
  onNavigate,
}: MoreSheetAccordionProps) {
  const { lang } = useLang();
  const auth = useAuth() as { user?: { roles?: string[]; tier?: string } };
  const isAdmin =
    auth?.user?.roles?.includes("operator") === true &&
    auth?.user?.tier === "admin";
  const filtered = filterNavItems(config, isAdmin);
  const sections = sidebarSections(filtered);

  const storageKey = `caresetu.moreSheet.${role}.openPanel`;
  const [openPanel, setOpenPanel] = useState<string | null>(null);

  useEffect(() => {
    try {
      setOpenPanel(sessionStorage.getItem(storageKey));
    } catch {
      setOpenPanel(null);
    }
  }, [storageKey]);

  useEffect(() => {
    try {
      if (openPanel) {
        sessionStorage.setItem(storageKey, openPanel);
      } else {
        sessionStorage.removeItem(storageKey);
      }
    } catch {
      // ignore storage failures
    }
  }, [openPanel, storageKey]);

  function toggle(key: string) {
    setOpenPanel((prev) => (prev === key ? null : key));
  }

  return (
    <div className="flex flex-col" data-testid="more-sheet-accordion">
      {sections.map((section) => {
        const key = section.labelKey ?? "ungrouped";
        if (!ACCORDION_SECTION_KEYS.has(key)) {
          return (
            <Fragment key={key}>
              {section.labelKey && (
                <p
                  className="px-2 pt-3 pb-1 text-[11px] font-semibold tracking-wide text-txt-muted uppercase"
                  data-testid={`more-section-${key}`}
                >
                  {
                    STRINGS[lang].nav.sections[
                      key as keyof typeof STRINGS.en.nav.sections
                    ]
                  }
                </p>
              )}
              {section.items.map((item) =>
                item.children?.length ? (
                  <SheetGroupNavItem
                    key={item.key}
                    item={item}
                    onNavigate={onNavigate}
                  />
                ) : (
                  <OverflowRow
                    key={item.key}
                    item={item}
                    label={STRINGS[lang].nav[item.labelKey]}
                    onNavigate={onNavigate}
                  />
                ),
              )}
            </Fragment>
          );
        }
        return (
          <AccordionPanel
            key={key}
            sectionKey={key}
            section={section}
            open={openPanel === key}
            onToggle={() => toggle(key)}
            onNavigate={onNavigate}
          />
        );
      })}
    </div>
  );
}

function AccordionPanel({
  sectionKey,
  section,
  open,
  onToggle,
  onNavigate,
}: {
  sectionKey: string;
  section: SidebarSection;
  open: boolean;
  onToggle: () => void;
  onNavigate: () => void;
}) {
  const { lang } = useLang();
  const strings = STRINGS[lang].nav;
  const panelId = useId();
  const headerId = useId();
  const label =
    section.labelKey != null
      ? STRINGS[lang].nav.sections[
          section.labelKey as keyof typeof STRINGS.en.nav.sections
        ]
      : null;

  return (
    <div
      data-testid={`more-accordion-${sectionKey}`}
      className="border-b border-hairline-soft"
    >
      <button
        type="button"
        id={headerId}
        onClick={(event) => {
          if (!event.defaultPrevented) onToggle();
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onToggle();
          }
        }}
        aria-expanded={open}
        aria-controls={panelId}
        data-testid={`more-section-${sectionKey}`}
        className="flex min-h-12 w-full items-center justify-between gap-2 rounded px-2 py-2 text-sm font-semibold text-txt"
      >
        <span className="flex flex-1 items-center gap-2">
          <span>{label}</span>
        </span>
        <span aria-hidden="true" className="text-txt-muted">
          {open ? "-" : "+"}
        </span>
      </button>
      <div
        id={panelId}
        data-open={open ? "" : undefined}
        aria-labelledby={headerId}
        data-testid={`more-panel-${sectionKey}`}
        className="grid transition-[grid-template-rows] duration-200 ease-in-out"
        style={{ gridTemplateRows: open ? "1fr" : "0fr" }}
      >
        <div className="overflow-hidden">
          <div className="flex flex-col pl-1">
            {section.items.map((item) =>
              item.children?.length ? (
                <SheetGroupNavItem
                  key={item.key}
                  item={item}
                  onNavigate={onNavigate}
                />
              ) : (
                <OverflowRow
                  key={item.key}
                  item={item}
                  label={strings[item.labelKey]}
                  onNavigate={onNavigate}
                />
              ),
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
