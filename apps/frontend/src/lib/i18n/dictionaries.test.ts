// PHASE-2.6 T03 (#194): bilingual parity gate for the string dictionaries
// (REQ-006, spec #191 testing decision 2). Any key missing from either
// locale - or present with a different shape (string vs function vs array,
// array length, function arity) - fails this suite mechanically. The
// detector self-tests below keep that failure mode demonstrable on demand:
// they feed deliberately broken copies through the same checker and assert
// it flags them.

import { describe, expect, it } from "vitest";

import { STRINGS, type Dictionary } from "./dictionaries";

function parityProblems(en: unknown, hi: unknown, path: string): string[] {
  if (Array.isArray(en) || Array.isArray(hi)) {
    if (!Array.isArray(en) || !Array.isArray(hi)) {
      return [`${path}: array in one locale only`];
    }
    if (en.length !== hi.length) {
      return [`${path}: array length ${en.length} (en) vs ${hi.length} (hi)`];
    }
    // Element-wise shape check: same length is not enough - element 0 of
    // one locale must have the same shape as element 0 of the other.
    const problems: string[] = [];
    for (let i = 0; i < en.length; i++) {
      problems.push(...parityProblems(en[i], hi[i], `${path}[${i}]`));
    }
    return problems;
  }
  if (typeof en === "function" || typeof hi === "function") {
    if (typeof en !== "function" || typeof hi !== "function") {
      return [`${path}: function in one locale only`];
    }
    if (en.length !== hi.length) {
      return [`${path}: arity ${en.length} (en) vs ${hi.length} (hi)`];
    }
    return [];
  }
  if (typeof en === "object" && en !== null && typeof hi === "object") {
    if (hi === null) return [`${path}: object missing from hi`];
    const problems: string[] = [];
    for (const key of new Set([...Object.keys(en), ...Object.keys(hi)])) {
      if (!(key in en)) {
        problems.push(`${path}.${key}: missing from en`);
        continue;
      }
      if (!(key in hi)) {
        problems.push(`${path}.${key}: missing from hi`);
        continue;
      }
      problems.push(
        ...parityProblems(
          (en as Record<string, unknown>)[key],
          (hi as Record<string, unknown>)[key],
          `${path}.${key}`,
        ),
      );
    }
    return problems;
  }
  if (typeof en !== typeof hi) {
    return [`${path}: type mismatch (${typeof en} vs ${typeof hi})`];
  }
  return [];
}

describe("bilingual dictionary parity (REQ-006, #194)", () => {
  it("has every key present in both locales with matching shape", () => {
    expect(parityProblems(STRINGS.en, STRINGS.hi, "")).toEqual([]);
  });

  it("ships exactly the en/hi locales", () => {
    expect(Object.keys(STRINGS).sort()).toEqual(["en", "hi"]);
  });
});

describe("parity detector self-test (#194 red/green proof)", () => {
  function brokenCopy(locale: Dictionary): Dictionary {
    // Shallow-clone one surface so deletions never touch the real table.
    return {
      ...locale,
      auth: { ...locale.auth } as Dictionary["auth"],
    };
  }

  it("flags a key deleted from the hi locale", () => {
    const broken = brokenCopy(STRINGS.hi);
    delete (broken.auth as Record<string, unknown>).brand;
    expect(parityProblems(STRINGS.en, broken, "")).toEqual([
      ".auth.brand: missing from hi",
    ]);
  });

  it("flags a key deleted from the en locale", () => {
    const broken = brokenCopy(STRINGS.en);
    delete (broken.auth as Record<string, unknown>).signOut;
    expect(parityProblems(broken, STRINGS.hi, "")).toEqual([
      ".auth.signOut: missing from en",
    ]);
  });

  it("flags a reshaped value (string replaced by a function)", () => {
    const broken = brokenCopy(STRINGS.en);
    (broken.auth as Record<string, unknown>).signOut = () => "Sign out";
    expect(parityProblems(broken, STRINGS.hi, "")).toEqual([
      ".auth.signOut: function in one locale only",
    ]);
  });

  it("flags an array whose length diverges between locales", () => {
    const broken = brokenCopy(STRINGS.hi);
    (broken.auth as Record<string, unknown>).valueProps = [
      ...(STRINGS.hi.auth.valueProps as string[]),
      "extra",
    ];
    expect(parityProblems(STRINGS.en, broken, "")).toEqual([
      ".auth.valueProps: array length 3 (en) vs 4 (hi)",
    ]);
  });

  it("flags a value whose type diverges inside an array", () => {
    const broken = brokenCopy(STRINGS.hi);
    (broken.auth.valueProps as string[])[0] = 42 as unknown as string;
    expect(parityProblems(STRINGS.en, broken, "")).toEqual([
      ".auth.valueProps[0]: type mismatch (string vs number)",
    ]);
  });
});
