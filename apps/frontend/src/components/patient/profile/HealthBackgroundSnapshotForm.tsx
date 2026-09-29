"use client";

// MOD-003 (FEAT-002 record), gated by MOD-004 (FEAT-002 consent), #549: the
// Health background zone's snapshot surface - the blood group plus the five
// free-form entry lists the patient authors about themselves (US-21/US-22), on
// the owner's own endpoint from #534.
//
// The one behaviour worth reading twice is the first-save confirmation. The
// backend stamps `acknowledge_phi` on the first acknowledged save and never
// re-asks (ADR-0018), so this surface asks exactly once, and only before that
// save: `acknowledged` from the read is the whole of what it knows about
// whether the question is still open. A later edit saves straight through with
// `acknowledge_phi: false` - present, because the field is required, and false,
// because re-granting on every edit is not what the patient agreed to.
//
// "Not now" is not an answer for good: it closes the sheet, keeps the typed
// draft, and leaves the question open for the next tap. Nothing is written
// while the question is open.
//
// A missing snapshot renders the empty state rather than a fabricated one, and a
// failed read offers a retry instead of a form - a blank form would invite the
// patient to retype a snapshot the API may already be holding, and the retype
// would look like a first save.

import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { HealthZoneFailureNotice } from "@/components/patient/profile/HealthZoneFailureNotice";
import { ApiError } from "@/lib/api-errors";
import { STRINGS, type Dictionary } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import {
  fetchHealthBackground,
  saveHealthBackground,
  type HealthBackground,
  type HealthBackgroundView,
} from "@/lib/health-background/api";
import {
  entriesToText,
  normalizeBloodGroup,
  textToEntries,
} from "@/lib/health-background/form";

type ZoneStrings = Dictionary["profileZones"];

const labelClass = "text-sm font-medium text-txt";

const inputClass =
  "mt-1 block h-9 w-full rounded-md border border-input bg-background px-3 text-sm text-txt shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring";

const areaClass =
  "mt-1 block w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-txt shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring";

/** The five entry lists, in the order the form presents them. */
const ENTRY_AREAS = [
  "conditions",
  "allergies",
  "medications",
  "immunizations",
  "family_history",
] as const;

type EntryArea = (typeof ENTRY_AREAS)[number];

/**
 * The dictionary keys that name each entry area. Written out rather than
 * derived from the field name, because the wire field is snake_case and the
 * copy is camelCase - and typed as a union so a key that stops existing in the
 * dictionary fails the build here instead of rendering nothing.
 */
type EntryCopyKey =
  | "conditionsLabel"
  | "conditionsPlaceholder"
  | "allergiesLabel"
  | "allergiesPlaceholder"
  | "medicationsLabel"
  | "medicationsPlaceholder"
  | "immunizationsLabel"
  | "immunizationsPlaceholder"
  | "familyHistoryLabel"
  | "familyHistoryPlaceholder";

const ENTRY_AREA_COPY: Record<
  EntryArea,
  { label: EntryCopyKey; placeholder: EntryCopyKey }
> = {
  conditions: {
    label: "conditionsLabel",
    placeholder: "conditionsPlaceholder",
  },
  allergies: { label: "allergiesLabel", placeholder: "allergiesPlaceholder" },
  medications: {
    label: "medicationsLabel",
    placeholder: "medicationsPlaceholder",
  },
  immunizations: {
    label: "immunizationsLabel",
    placeholder: "immunizationsPlaceholder",
  },
  family_history: {
    label: "familyHistoryLabel",
    placeholder: "familyHistoryPlaceholder",
  },
};

/** The five areas as the textarea holds them: one entry per line. */
type AreaText = Record<EntryArea, string>;

const EMPTY_AREA_TEXT: AreaText = {
  conditions: "",
  allergies: "",
  medications: "",
  immunizations: "",
  family_history: "",
};

function areaTextFrom(background: HealthBackground | null): AreaText {
  const source = background ?? {
    blood_group: null,
    conditions: [],
    allergies: [],
    medications: [],
    immunizations: [],
    family_history: [],
  };
  return {
    conditions: entriesToText(source.conditions),
    allergies: entriesToText(source.allergies),
    medications: entriesToText(source.medications),
    immunizations: entriesToText(source.immunizations),
    family_history: entriesToText(source.family_history),
  };
}

function backgroundFrom(bloodGroup: string, areas: AreaText): HealthBackground {
  return {
    blood_group: normalizeBloodGroup(bloodGroup),
    conditions: textToEntries(areas.conditions),
    allergies: textToEntries(areas.allergies),
    medications: textToEntries(areas.medications),
    immunizations: textToEntries(areas.immunizations),
    family_history: textToEntries(areas.family_history),
  };
}

/** Trace id off a failure so a support conversation can start from the alert. */
function traceIdOf(error: unknown): string | undefined {
  return error instanceof ApiError && error.traceId ? error.traceId : undefined;
}

export function HealthBackgroundSnapshotForm() {
  const { lang } = useLang();
  const t: ZoneStrings = STRINGS[lang].profileZones;

  // `null` means "not read yet", which is a loading state, not an empty one.
  const [view, setView] = useState<HealthBackgroundView | null>(null);
  const [loadFailure, setLoadFailure] = useState<{ traceId?: string } | null>(
    null,
  );
  const [bloodGroup, setBloodGroup] = useState("");
  const [areas, setAreas] = useState<AreaText>(EMPTY_AREA_TEXT);
  // The read's answer on whether the one-time confirmation is still open, and
  // the local answer once the patient has given it. Either one being true means
  // never ask again in this visit.
  const [acknowledged, setAcknowledged] = useState(false);
  const [consentOpen, setConsentOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveFailure, setSaveFailure] = useState<{ traceId?: string } | null>(
    null,
  );
  const [saved, setSaved] = useState(false);
  // The Idempotency-Key of the attempt in flight, kept so a retry after a lost
  // response replays the same mutation instead of writing it twice. The snapshot
  // write converges, so a duplicate is harmless here - but the same habit on an
  // append-only series would be a second clinical fact, which is why the key
  // lives in one place and both surfaces hold it.
  const pendingSaveKey = useRef<string | undefined>(undefined);

  /**
   * Any edit to the draft spends the key. A key identifies ONE mutation: sent
   * again with a different body the gateway replays the ORIGINAL stored view
   * and reports success, so a corrected draft would silently go in as the value
   * the patient just changed. Editing is a new attempt with a new key.
   */
  function editDraft(next: { bloodGroup?: string; areas?: AreaText }) {
    pendingSaveKey.current = undefined;
    setSaved(false);
    if (next.bloodGroup !== undefined) setBloodGroup(next.bloodGroup);
    if (next.areas !== undefined) setAreas(next.areas);
  }

  const load = useCallback(async () => {
    setLoadFailure(null);
    try {
      const read = await fetchHealthBackground();
      setView(read);
      setAcknowledged(read.acknowledged);
      setBloodGroup(read.background?.blood_group ?? "");
      setAreas(areaTextFrom(read.background));
    } catch (err) {
      // No form over a failed read: a blank form would invite the patient to
      // retype a snapshot the API may already be holding, and the retype would
      // look like a first save.
      setLoadFailure({ traceId: traceIdOf(err) });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function commit(next: HealthBackground, acknowledgePhi: boolean) {
    setSaving(true);
    setSaveFailure(null);
    setSaved(false);
    const key = pendingSaveKey.current ?? crypto.randomUUID();
    pendingSaveKey.current = key;
    try {
      const storedView = await saveHealthBackground(next, {
        acknowledgePhi,
        retryKey: key,
      });
      // The stored answer is the source of truth from here: the API is what
      // decides the acknowledgment happened, not the tap that asked for it.
      setView(storedView);
      setAcknowledged(storedView.acknowledged);
      pendingSaveKey.current = undefined;
      setSaved(true);
    } catch (err) {
      // The key is deliberately kept: the same tap retries the same mutation
      // rather than minting a new one. The draft stays on screen, and the
      // acknowledgment stays unanswered, so a refused first save asks again
      // rather than pretending it was recorded.
      if (
        err instanceof ApiError &&
        err.code === "HEALTH_BACKGROUND_ACK_REQUIRED"
      ) {
        // The API is the authority on whether the snapshot has been
        // acknowledged, and a save can reach it unacknowledged from either
        // direction: the read that gated this tap may have been stale, or the
        // backend may have lost the acknowledgment. Either way the answer is a
        // question, not a failure - so the sheet is asked again rather than
        // reported as a failed write, which is what the patient did nothing
        // wrong to cause.
        setConsentOpen(true);
      } else {
        setSaveFailure({ traceId: traceIdOf(err) });
      }
    } finally {
      setSaving(false);
    }
  }

  function handleSave() {
    if (saving) return;
    setSaveFailure(null);
    // Nothing is written while the question is open, and the question only
    // opens while it is unanswered.
    if (!acknowledged) {
      setConsentOpen(true);
      return;
    }
    void commit(backgroundFrom(bloodGroup, areas), false);
  }

  function handleConsentConfirm() {
    if (saving) return;
    setConsentOpen(false);
    // The pending value is read from the live form at the moment of the answer,
    // so an edit typed between asking and answering is not lost.
    void commit(backgroundFrom(bloodGroup, areas), true);
  }

  return (
    <div data-testid="ps-hb-snapshot">
      {view === null && loadFailure === null && (
        <p
          data-testid="ps-hb-loading"
          className="text-sm text-txt-muted"
          role="status"
        >
          {t.healthLoading}
        </p>
      )}

      {loadFailure !== null && (
        <HealthZoneFailureNotice
          message={t.healthLoadFailed}
          retryLabel={t.healthRetry}
          failure={loadFailure}
          onRetry={() => void load()}
          testId="ps-hb-load-failed"
          retryTestId="ps-hb-retry"
        />
      )}

      {view !== null && !view.set && (
        <p data-testid="ps-health-pending" className="text-sm text-txt-muted">
          {t.healthPending}
        </p>
      )}

      {view !== null && (
        <div data-testid="ps-hb-snapshot-form" className="flex flex-col gap-4">
          <div>
            <label htmlFor="ps-hb-blood-group" className={labelClass}>
              {t.bloodGroupLabel}
            </label>
            <input
              id="ps-hb-blood-group"
              data-testid="ps-hb-blood-group"
              type="text"
              className={inputClass}
              placeholder={t.bloodGroupPlaceholder}
              value={bloodGroup}
              onChange={(e) => {
                editDraft({ bloodGroup: e.target.value });
              }}
            />
          </div>

          {ENTRY_AREAS.map((area) => (
            <div key={area}>
              <label htmlFor={`ps-hb-${area}`} className={labelClass}>
                {t[ENTRY_AREA_COPY[area].label]}
              </label>
              <textarea
                id={`ps-hb-${area}`}
                data-testid={`ps-hb-${area}`}
                rows={3}
                className={areaClass}
                placeholder={t[ENTRY_AREA_COPY[area].placeholder]}
                value={areas[area]}
                aria-describedby={`ps-hb-${area}-hint`}
                onChange={(e) => {
                  editDraft({
                    areas: { ...areas, [area]: e.target.value },
                  });
                }}
              />
              <p
                id={`ps-hb-${area}-hint`}
                className="mt-1 text-xs text-txt-muted"
              >
                {t.listHint}
              </p>
            </div>
          ))}

          <div className="flex justify-end">
            <Button
              type="button"
              data-testid="ps-hb-snapshot-save"
              onClick={handleSave}
              loading={saving}
            >
              {t.snapshotSave}
            </Button>
          </div>

          {saved && (
            <p
              role="status"
              data-testid="ps-hb-saved"
              className="rounded-md border border-success-soft bg-success-soft px-3 py-2 text-sm text-success-text"
            >
              {/* Once acknowledged, every save changes who can see an edit -
                  which is the whole point of the zone - so the confirmation
                  follows each one rather than only the first. */}
              {acknowledged && view.set
                ? t.snapshotSharedNote
                : t.snapshotSaved}
            </p>
          )}

          {saveFailure !== null && (
            <p
              role="alert"
              data-testid="ps-hb-save-failed"
              className="rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-sm text-danger"
            >
              {t.snapshotSaveFailed}
              {saveFailure.traceId && (
                <span className="ml-1 font-mono text-xs">
                  ({saveFailure.traceId})
                </span>
              )}
            </p>
          )}
        </div>
      )}

      {/* ---------------------------------------------------------------
          The one-time first-save confirmation. It opens from the save
          control and only while the acknowledgment is still open; the
          backend stamps it once, so this never becomes a recurring
          prompt.
      ----------------------------------------------------------------*/}
      <Sheet open={consentOpen} onOpenChange={(open) => setConsentOpen(open)}>
        <SheetContent side="bottom" data-testid="ps-hb-consent-sheet">
          <SheetHeader>
            <SheetTitle data-testid="ps-hb-consent-title">
              {t.healthConsentTitle}
            </SheetTitle>
            <SheetDescription asChild>
              <div className="flex flex-col gap-2 text-sm text-txt">
                <p>{t.healthConsentBody}</p>
                <p className="text-txt-muted">{t.healthConsentRecall}</p>
              </div>
            </SheetDescription>
          </SheetHeader>
          <SheetFooter className="mt-4 flex-row gap-2">
            <Button
              type="button"
              data-testid="ps-hb-consent-confirm"
              onClick={handleConsentConfirm}
              loading={saving}
            >
              {t.healthConsentConfirm}
            </Button>
            <Button
              type="button"
              variant="ghost"
              data-testid="ps-hb-consent-cancel"
              onClick={() => setConsentOpen(false)}
            >
              {t.healthConsentCancel}
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </div>
  );
}
