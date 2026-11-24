"use client";

// #967 (FEAT-004): the directory Filter Sheet bottom sheet (PROTO-PHASE-6
// filter-sheet markup as the visual binding). Sections vary by partner type:
// doctors get Specialty checkboxes with client-side counts wired to
// `?specialty=`, labs get Test-type checkboxes with counts plus cosmetic
// Services, chemists get cosmetic Services plus an Availability radio. Every
// control is fully styled and interactive; only `specialty` (and the cosmetic
// `location` draft) commit to the URL - the rest is marked TODO(BACKEND)
// until its query params exist.

import { useEffect, useRef, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import type { ProviderType } from "@/lib/directory/links";
import {
  DIRECTORIES_SPECIALTIES,
  type DirectoryEntry,
  type Specialty,
} from "@/lib/directory/search";
import { specialtyLabel } from "@/lib/directory/specialtyLabel";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

/** Commit payload the parent DirectoryBrowser applies to the URL - the single
 * shape of "filters the sheet can change" (the sheet never pins partner type
 * itself but Reset clears it on an all-types browse). */
export type FilterSheetCommit = {
  type?: ProviderType | null;
  specialty?: Specialty | null;
  location?: string | null;
  q?: string | null;
};

/** TODO(BACKEND): lab test-type counts are approximated by matching the
 * loaded entries' practice names - a real facet count needs its own endpoint. */
const TEST_TYPE_KEYWORDS: Record<string, string[]> = {
  blood_tests: ["blood"],
  x_ray: ["x-ray", "xray"],
  full_body: ["full body"],
  pathology: ["path"],
  ecg: ["ecg"],
};

type OptionId = string;

const CONSULT_OPTIONS: {
  id: OptionId;
  labelKey: "consultAll" | "consultInClinic" | "consultOnline";
}[] = [
  { id: "all", labelKey: "consultAll" },
  { id: "in_clinic", labelKey: "consultInClinic" },
  { id: "online", labelKey: "consultOnline" },
];

const AVAILABILITY_OPTIONS: {
  id: OptionId;
  labelKey: "availabilityAnyTime" | "availabilityOpenNow";
}[] = [
  { id: "any_time", labelKey: "availabilityAnyTime" },
  { id: "open_now", labelKey: "availabilityOpenNow" },
];

function countSpecialties(items: DirectoryEntry[]): Map<Specialty, number> {
  const counts = new Map<Specialty, number>();
  for (const specialty of DIRECTORIES_SPECIALTIES) counts.set(specialty, 0);
  for (const item of items) {
    if (
      item.specialty &&
      (DIRECTORIES_SPECIALTIES as readonly string[]).includes(item.specialty)
    ) {
      const key = item.specialty as Specialty;
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
  }
  return counts;
}

function countTestTypes(
  items: DirectoryEntry[],
  ids: readonly { id: string }[],
): Map<string, number> {
  const counts = new Map<string, number>();
  for (const { id } of ids) {
    const keywords = TEST_TYPE_KEYWORDS[id] ?? [];
    counts.set(
      id,
      items.filter((item) => {
        const name = (item.practice_name ?? "").toLowerCase();
        return keywords.some((keyword) => name.includes(keyword));
      }).length,
    );
  }
  return counts;
}

const CHECK_ROW_CLASS =
  "flex min-h-[44px] cursor-pointer items-center gap-3 rounded-md px-2 transition-colors hover:bg-hairline-soft";

/** One checkbox row shared by the specialty / test-type / service sections;
 * `data-section` tells tests and the DOM which section a row belongs to. */
function CheckRow({
  section,
  label,
  checked,
  onChange,
  count,
}: {
  section: "specialty" | "test-type" | "service";
  label: string;
  checked: boolean;
  onChange: () => void;
  /** Present only where the prototype shows a count (specialty, test type). */
  count?: number;
}) {
  return (
    <label
      data-testid="filter-check-row"
      data-section={section}
      className={CHECK_ROW_CLASS}
    >
      <input
        type="checkbox"
        data-testid="filter-checkbox"
        checked={checked}
        onChange={onChange}
        className="h-5 w-5 shrink-0 rounded border-hairline accent-accent"
      />
      <span className="flex-1 text-sm text-txt">{label}</span>
      {count !== undefined && (
        <span data-testid="filter-count" className="text-sm text-txt-muted">
          {count}
        </span>
      )}
    </label>
  );
}

/** Segmented pill radio group (consult type / availability). */
function SegmentedRadio({
  label,
  columns,
  value,
  options,
  onChange,
}: {
  label: string;
  columns: 2 | 3;
  value: OptionId;
  options: { id: OptionId; label: string }[];
  onChange: (id: OptionId) => void;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={`grid gap-1 rounded-full border border-hairline bg-hairline-soft p-1 ${
        columns === 2 ? "grid-cols-2" : "grid-cols-3"
      }`}
    >
      {options.map((option) => {
        const active = value === option.id;
        return (
          <button
            key={option.id}
            type="button"
            role="radio"
            aria-checked={active}
            data-testid="radio-option"
            onClick={() => onChange(option.id)}
            className={`min-h-[44px] rounded-full text-sm font-medium transition-colors ${
              active ? "bg-surface text-txt shadow-card" : "text-txt-sub"
            }`}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

export function FilterSheet({
  open,
  onOpenChange,
  sectionType,
  specialty,
  location,
  items,
  onCommit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Which sections to render: the pinned variant type, else the committed
   * `type` param, defaulting to the doctor sections on an all-types browse. */
  sectionType: ProviderType;
  specialty: Specialty | null;
  location: string | null;
  items: DirectoryEntry[];
  onCommit: (next: FilterSheetCommit) => void;
}) {
  const { lang } = useLang();
  const t = STRINGS[lang].directory;
  const filterSheet = t.filterSheet;

  // Local UI state: multi-check specialty (first checked wires to the URL),
  // the location draft, and the cosmetic controls. Seeded once per open so a
  // URL commit triggered from inside the sheet does not wipe sibling checks.
  const [checkedSpecialties, setCheckedSpecialties] = useState<Specialty[]>([]);
  const [locationDraft, setLocationDraft] = useState("");
  const [consultType, setConsultType] = useState<OptionId>("all");
  const [availability, setAvailability] = useState<OptionId>("any_time");
  const [checkedServices, setCheckedServices] = useState<OptionId[]>([]);
  const [checkedTestTypes, setCheckedTestTypes] = useState<OptionId[]>([]);
  const seededRef = useRef(false);

  useEffect(() => {
    if (!open) {
      seededRef.current = false;
      return;
    }
    if (seededRef.current) return;
    seededRef.current = true;
    setCheckedSpecialties(specialty ? [specialty] : []);
    setLocationDraft(location ?? "");
    setConsultType("all");
    setAvailability("any_time");
    setCheckedServices([]);
    setCheckedTestTypes([]);
  }, [open, specialty, location]);

  const specialtyCounts = countSpecialties(items);
  const testTypeCounts = countTestTypes(items, filterSheet.labTestTypes);
  const resultCount = items.length;
  const noun =
    sectionType === "doctor"
      ? filterSheet.nounDoctors
      : sectionType === "lab"
        ? filterSheet.nounLabs
        : filterSheet.nounChemists;

  function toggleSpecialty(next: Specialty) {
    const checked = checkedSpecialties.includes(next)
      ? checkedSpecialties.filter((value) => value !== next)
      : [...checkedSpecialties, next];
    setCheckedSpecialties(checked);
    // Wire the first checked specialty (closed pick-list order) to
    // `?specialty=`; multi-select beyond that is cosmetic until the backend
    // accepts a list (TODO(BACKEND)).
    const first =
      DIRECTORIES_SPECIALTIES.find((value) => checked.includes(value)) ?? null;
    onCommit({ specialty: first });
  }

  function toggleInList(list: OptionId[], id: OptionId): OptionId[] {
    return list.includes(id)
      ? list.filter((value) => value !== id)
      : [...list, id];
  }

  function commitLocation() {
    const value = locationDraft.trim();
    const current = location ?? "";
    if (value !== current) onCommit({ location: value || null });
  }

  function reset() {
    setCheckedSpecialties([]);
    setLocationDraft("");
    setConsultType("all");
    setAvailability("any_time");
    setCheckedServices([]);
    setCheckedTestTypes([]);
    onCommit({ type: null, q: null, specialty: null, location: null });
  }

  function show() {
    commitLocation();
    onOpenChange(false);
  }

  const sectionLabelClass =
    "text-xs font-semibold uppercase tracking-wide text-txt-muted";

  const sectionLabel = (label: string): ReactNode => (
    <span className={sectionLabelClass}>{label}</span>
  );

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="bottom"
        data-testid="filter-sheet"
        className="mx-auto flex max-h-[85dvh] max-w-lg flex-col overflow-y-auto rounded-t-lg p-0 sm:max-w-lg"
      >
        <div
          aria-hidden="true"
          className="mx-auto mt-2 h-1 w-10 shrink-0 rounded-full bg-hairline"
        />
        <SheetHeader className="shrink-0 px-4 pb-1 pt-3 text-left">
          <SheetTitle className="text-lg">{filterSheet.title}</SheetTitle>
          <SheetDescription>{filterSheet.description}</SheetDescription>
        </SheetHeader>

        <div className="flex min-h-0 flex-1 flex-col gap-5 px-4 pb-4">
          {/* Location - cosmetic draft committed on blur/Show (TODO(BACKEND):
              geo filtering needs lat/lng, not a free-text area). */}
          <div className="flex flex-col gap-2">
            {sectionLabel(filterSheet.locationLabel)}
            <input
              type="text"
              data-testid="filter-location-input"
              value={locationDraft}
              placeholder={filterSheet.locationPlaceholder}
              onChange={(event) => setLocationDraft(event.target.value)}
              onBlur={commitLocation}
              className="min-h-[44px] rounded-md border border-hairline bg-surface px-3 py-2 text-sm text-txt placeholder:text-txt-muted focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>

          {sectionType === "doctor" && (
            <>
              <div className="flex flex-col gap-1">
                {sectionLabel(filterSheet.specialtyLabel)}
                <div className="flex flex-col">
                  {DIRECTORIES_SPECIALTIES.map((value) => (
                    <CheckRow
                      key={value}
                      section="specialty"
                      label={specialtyLabel(lang, value)}
                      checked={checkedSpecialties.includes(value)}
                      onChange={() => toggleSpecialty(value)}
                      count={specialtyCounts.get(value) ?? 0}
                    />
                  ))}
                </div>
              </div>

              {/* Consult-type radio - cosmetic (TODO(BACKEND): no consult-type
                  query param exists on /v1/directory/search yet). */}
              <div className="flex flex-col gap-2">
                {sectionLabel(filterSheet.consultTypeLabel)}
                <SegmentedRadio
                  label={filterSheet.consultTypeLabel}
                  columns={3}
                  value={consultType}
                  options={CONSULT_OPTIONS.map((option) => ({
                    id: option.id,
                    label: filterSheet[option.labelKey],
                  }))}
                  onChange={setConsultType}
                />
              </div>
            </>
          )}

          {sectionType === "lab" && (
            <>
              <div className="flex flex-col gap-1">
                {sectionLabel(filterSheet.testTypeLabel)}
                <div className="flex flex-col">
                  {filterSheet.labTestTypes.map(({ id, label }) => (
                    <CheckRow
                      key={id}
                      section="test-type"
                      label={label}
                      checked={checkedTestTypes.includes(id)}
                      onChange={() =>
                        setCheckedTestTypes((prev) => toggleInList(prev, id))
                      }
                      count={testTypeCounts.get(id) ?? 0}
                    />
                  ))}
                </div>
              </div>

              {/* Lab services - cosmetic (TODO(BACKEND)). */}
              <div className="flex flex-col gap-1">
                {sectionLabel(filterSheet.servicesLabel)}
                <div className="flex flex-col">
                  {filterSheet.labServices.map(({ id, label }) => (
                    <CheckRow
                      key={id}
                      section="service"
                      label={label}
                      checked={checkedServices.includes(id)}
                      onChange={() =>
                        setCheckedServices((prev) => toggleInList(prev, id))
                      }
                    />
                  ))}
                </div>
              </div>
            </>
          )}

          {sectionType === "chemist" && (
            <>
              {/* Chemist services - cosmetic (TODO(BACKEND)). */}
              <div className="flex flex-col gap-1">
                {sectionLabel(filterSheet.servicesLabel)}
                <div className="flex flex-col">
                  {filterSheet.chemistServices.map(({ id, label }) => (
                    <CheckRow
                      key={id}
                      section="service"
                      label={label}
                      checked={checkedServices.includes(id)}
                      onChange={() =>
                        setCheckedServices((prev) => toggleInList(prev, id))
                      }
                    />
                  ))}
                </div>
              </div>

              {/* Availability radio - cosmetic (TODO(BACKEND)). */}
              <div className="flex flex-col gap-2">
                {sectionLabel(filterSheet.availabilityLabel)}
                <SegmentedRadio
                  label={filterSheet.availabilityLabel}
                  columns={2}
                  value={availability}
                  options={AVAILABILITY_OPTIONS.map((option) => ({
                    id: option.id,
                    label: filterSheet[option.labelKey],
                  }))}
                  onChange={setAvailability}
                />
              </div>
            </>
          )}
        </div>

        <div className="sticky bottom-0 shrink-0 gap-3 border-t border-hairline bg-surface px-4 py-3 sm:flex">
          <Button
            type="button"
            variant="secondary"
            data-testid="filter-reset"
            onClick={reset}
            className="min-h-12 w-full sm:flex-1"
          >
            {filterSheet.reset}
          </Button>
          <Button
            type="button"
            data-testid="filter-show"
            onClick={show}
            className="mt-2 min-h-12 w-full sm:mt-0 sm:flex-1"
          >
            {filterSheet.showCount(resultCount, noun)}
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
