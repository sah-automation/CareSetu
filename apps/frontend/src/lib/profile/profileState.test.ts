// PHASE-2.6 T13 (#204): unit coverage for the client-side profile draft,
// required-basics validation, completion meter, and the §5.9 gating matrix.

import { beforeEach, describe, expect, it } from "vitest";

import {
  __resetNudgeDismissalsForTests,
  areaComplete,
  basicsComplete,
  dismissNudge,
  evaluateGate,
  initialDraft,
  isNudgeDismissed,
  loadDraft,
  missingNudgeGroups,
  profileCompleteness,
  saveDraft,
  step1Errors,
  type ProfileDraft,
} from "./profileState";

function draftWith(partial: Partial<ProfileDraft>): ProfileDraft {
  return { ...initialDraft(), ...partial };
}

describe("initialDraft", () => {
  it("starts every field unset with language defaulted to en (spec #191 D1)", () => {
    expect(initialDraft()).toEqual({
      name: "",
      age: "",
      gender: "",
      language: "en",
      trackBp: false,
      trackSugar: false,
      photoFileName: "",
      area: "",
      emergencyContact: "",
    });
  });
});

describe("required-basics validation (step 1)", () => {
  it("flags name, age and gender on an empty draft", () => {
    const errors = step1Errors(initialDraft());
    expect(errors.nameRequired).toBe(true);
    expect(errors.ageRequired).toBe(true);
    expect(errors.genderRequired).toBe(true);
    expect(basicsComplete(initialDraft())).toBe(false);
  });

  it("treats whitespace-only input as missing", () => {
    const errors = step1Errors(draftWith({ name: "   ", age: "  " }));
    expect(errors.nameRequired).toBe(true);
    expect(errors.ageRequired).toBe(true);
  });

  it("rejects non-numeric and out-of-range ages as invalid, not missing", () => {
    for (const bad of ["abc", "0", "-3", "121", "34.5"]) {
      const errors = step1Errors(draftWith({ age: bad }));
      expect(errors.ageRequired).toBe(false);
      expect(errors.ageInvalid).toBe(true);
    }
    expect(step1Errors(draftWith({ age: "120" })).ageInvalid).toBe(false);
    expect(step1Errors(draftWith({ age: "1" })).ageInvalid).toBe(false);
  });

  it("accepts a draft once name, a valid age and a gender are present", () => {
    const complete = draftWith({
      name: "Asha Devi",
      age: "30",
      gender: "female",
    });
    expect(step1Errors(complete)).toEqual({
      nameRequired: false,
      ageRequired: false,
      ageInvalid: false,
      genderRequired: false,
    });
    expect(basicsComplete(complete)).toBe(true);
  });

  it("never blocks on language: it always carries the D1 default", () => {
    // Language is asked explicitly in step 1 but pre-answers itself from the
    // D1 default, so it can never be the reason basics stay incomplete.
    expect(basicsComplete(draftWith({ language: "hi" }))).toBe(false);
  });

  it("does not count an area-only draft as care-ready", () => {
    expect(basicsComplete(draftWith({ area: "Bishrampur" }))).toBe(false);
  });
});

describe("completion meter", () => {
  it("is 0% on the empty draft", () => {
    expect(profileCompleteness(initialDraft())).toBe(0);
  });

  it("is 100% only when every collectable item is present", () => {
    const full = draftWith({
      name: "Asha Devi",
      age: "30",
      gender: "other",
      trackBp: true,
      photoFileName: "me.jpg",
      area: "Bishrampur",
      emergencyContact: "+91 98765 43210",
    });
    expect(profileCompleteness(full)).toBe(100);
  });

  it("counts valid fields only and moves monotonically toward 100%", () => {
    const one = profileCompleteness(draftWith({ name: "Asha" }));
    expect(one).toBeGreaterThan(0);
    expect(one).toBeLessThan(100);

    // Garbage must not advance the meter past what validity allows.
    expect(profileCompleteness(draftWith({ age: "garbage" }))).toBe(0);

    const two = profileCompleteness(
      draftWith({ name: "Asha", age: "30", gender: "male" }),
    );
    expect(two).toBeGreaterThan(one);
    expect(two).toBeLessThan(100);
  });
});

describe("gating matrix (blueprint §5.9)", () => {
  it("never gates browsing Find Care or My Record - even fully empty", () => {
    const empty = initialDraft();
    expect(evaluateGate("findCare", empty)).toBeNull();
    expect(evaluateGate("viewRecord", empty)).toBeNull();
  });

  it("gates intake and booking on basics only", () => {
    const empty = initialDraft();
    expect(evaluateGate("intake", empty)).toBe("basics");
    expect(evaluateGate("booking", empty)).toBe("basics");

    const named = draftWith({
      name: "Asha Devi",
      age: "30",
      gender: "female",
    });
    // Basics clear the gate even with no area/photo anywhere.
    expect(evaluateGate("intake", named)).toBeNull();
    expect(evaluateGate("booking", named)).toBeNull();
  });

  it("gates medicine-delivery checkout on area only", () => {
    const empty = initialDraft();
    expect(evaluateGate("medicineCheckout", empty)).toBe("area");

    // Area alone unblocks checkout - basics are not its gate.
    const located = draftWith({ area: "Bishrampur, Daltonganj" });
    expect(evaluateGate("medicineCheckout", located)).toBeNull();
  });

  it("keeps intake gating distinct from checkout gating", () => {
    const namedButUnlocated = draftWith({
      name: "Asha",
      age: "30",
      gender: "female",
    });
    expect(evaluateGate("intake", namedButUnlocated)).toBeNull();
    expect(evaluateGate("medicineCheckout", namedButUnlocated)).toBe("area");
  });

  it("agrees with the field predicates it derives from", () => {
    const partial = draftWith({ name: "Asha" });
    expect(areaComplete(partial)).toBe(false);
    expect(areaComplete(draftWith({ area: "  " }))).toBe(false);
    expect(areaComplete(draftWith({ area: " Bishrampur " }))).toBe(true);
  });
});

describe("nudge groups (skipped items resurface on Home)", () => {
  it("reports every group while the draft is empty", () => {
    expect(missingNudgeGroups(initialDraft())).toEqual([
      "basics",
      "tracking",
      "photo",
      "area",
      "emergency",
    ]);
  });

  it("drops a group once its item is filled", () => {
    expect(missingNudgeGroups(draftWith({ trackSugar: true }))).not.toContain(
      "tracking",
    );
    expect(missingNudgeGroups(draftWith({ area: "Bishrampur" }))).not.toContain(
      "area",
    );
    expect(
      missingNudgeGroups(draftWith({ emergencyContact: "+91" })),
    ).not.toContain("emergency");
    expect(
      missingNudgeGroups(draftWith({ photoFileName: "me.jpg" })),
    ).not.toContain("photo");
  });

  it("reports none when the draft is fully complete", () => {
    expect(missingNudgeGroups(loadDraftFrom(fullDraft()))).toEqual([]);
  });
});

describe("nudge dismissal memory (session-scoped, never permanent)", () => {
  beforeEach(() => {
    window.localStorage.clear();
    __resetNudgeDismissalsForTests();
  });

  it("starts with nothing dismissed", () => {
    expect(isNudgeDismissed("area")).toBe(false);
  });

  it("hides a dismissed group without touching the others", () => {
    dismissNudge("photo");
    expect(isNudgeDismissed("photo")).toBe(true);
    expect(isNudgeDismissed("basics")).toBe(false);
  });

  it("re-shows a group in a fresh session (memory dies with the page)", () => {
    dismissNudge("emergency");
    expect(isNudgeDismissed("emergency")).toBe(true);
    // No localStorage write: dismissal is deliberately not durable - a later
    // visit gets its gentle reminder again.
    expect(window.localStorage.getItem("caresetu.profile.draft")).toBeNull();
  });
});

describe("localStorage persistence", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("round-trips a draft through save/load", () => {
    const draft = draftWith({ name: "Asha Devi", language: "hi" });
    saveDraft(draft);
    expect(loadDraft()).toEqual(draft);
  });

  it("falls back to the initial draft when nothing is stored", () => {
    expect(loadDraft()).toEqual(initialDraft());
  });

  it("falls back to the initial draft when storage holds garbage", () => {
    window.localStorage.setItem("caresetu.profile.draft", "{not json");
    expect(loadDraft()).toEqual(initialDraft());
  });
});

// Helpers pinned below the suites so the file reads tests-first.

function fullDraft(): string {
  return JSON.stringify(
    draftWith({
      name: "Asha Devi",
      age: "30",
      gender: "female",
      trackBp: true,
      photoFileName: "me.jpg",
      area: "Bishrampur",
      emergencyContact: "+91",
    }),
  );
}

function loadDraftFrom(serialized: string): ProfileDraft {
  window.localStorage.setItem("caresetu.profile.draft", serialized);
  return loadDraft();
}
