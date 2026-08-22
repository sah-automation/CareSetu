import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import tailwindConfig from "../../tailwind.config";

// Contract gates for PHASE-2.6 T02 (#193, FEAT-006): resolved brand tokens,
// Mukta typography, single palette source, reduced-motion kill switch.

const here = (rel: string) => new URL(rel, import.meta.url);
const readUrl = (url: URL) => readFileSync(url, "utf8");

const tokensCss = readUrl(here("./tokens.css"));
const globalsCss = readUrl(here("./globals.css"));
const layoutTsx = readUrl(here("./layout.tsx"));
const wizardCss = readUrl(here("../components/auth/otp/otpShared.module.css"));

// Color-shaped hexes only (6/8 digits): prose refs like "#193" must not trip.
const HEX_COLOR = /#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{8}\b/;

const BRAND_HEXES: Record<string, string> = {
  "accent teal primary": "#0f766e",
  "accent teal hover": "#115e59",
  "accent teal tint": "#f0fdfa",
  "accent teal ring": "#99f6e4",
  "warm saffron": "#c2410c",
  "warm saffron mid": "#ea580c",
  "warm saffron soft": "#fff7ed",
};

// Seeded cyan accent set that must be gone everywhere after migration.
const SEEDED_CYAN_HEXES = ["#0e7490", "#155e75", "#ecfeff", "#bae6fd"];

function* walkSources(dir: string): Generator<string> {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const child = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (child.includes("node_modules")) continue;
      yield* walkSources(child);
    } else {
      yield child;
    }
  }
}

const SELF = fileURLToPath(here("./design-tokens.test.ts"));

function sourceFiles(filter: (f: string) => boolean): string[] {
  const srcRoot = fileURLToPath(here("../"));
  return [...walkSources(srcRoot)].filter((f) => filter(f) && f !== SELF);
}

function cssFiles(): string[] {
  return sourceFiles((f) => f.endsWith(".css") && !f.endsWith("tokens.css"));
}

function allSourceFiles(): string[] {
  return sourceFiles((f) => /\.(css|tsx?)$/.test(f));
}

function definedVarNames(content: string): Set<string> {
  const names = new Set<string>();
  for (const m of content.matchAll(/(--[a-zA-Z0-9-]+)\s*:/g)) names.add(m[1]);
  return names;
}

describe("resolved brand palette (#193)", () => {
  it("defines every resolved brand hex exactly once, in tokens.css", () => {
    for (const [role, hex] of Object.entries(BRAND_HEXES)) {
      expect(tokensCss, `missing ${role} ${hex}`).toContain(hex);
      expect(
        tokensCss.match(new RegExp(hex, "gi"))?.length ?? 0,
        `${hex} duplicated inside tokens.css`,
      ).toBe(1);
    }
    expect(tokensCss).toContain("--warn-soft: #fef3c7");
    expect(tokensCss).toContain("--warn-text: #92400e");
  });

  it("leaves the old seeded cyan accent nowhere in the app", () => {
    for (const file of allSourceFiles()) {
      const content = readFileSync(file, "utf8");
      for (const hex of SEEDED_CYAN_HEXES) {
        expect(content, `${file} still defines ${hex}`).not.toContain(hex);
      }
    }
  });
});

describe("single palette source (#193)", () => {
  it("tailwind config consumes CSS variables, never hexes", () => {
    const colors = tailwindConfig.theme?.extend?.colors ?? {};
    const leaves = colorLeaves(colors);
    expect(leaves.length).toBeGreaterThan(0);
    for (const value of leaves) {
      expect(value.startsWith("var(--"), `non-var token: ${value}`).toBe(true);
    }
    expect(JSON.stringify(tailwindConfig.theme)).not.toMatch(HEX_COLOR);
  });

  it("brand hexes are defined only in tokens.css", () => {
    for (const file of cssFiles()) {
      const content = readFileSync(file, "utf8");
      for (const hex of Object.values(BRAND_HEXES)) {
        expect(content, `${file} redefines ${hex}`).not.toContain(hex);
      }
    }
  });

  it("every var() reference in app CSS resolves to a definition", () => {
    // Runtime-injected by next/font on <html>, not statically definable.
    const injected = new Set(["--font-mukta"]);
    const tokenVars = definedVarNames(tokensCss);
    for (const file of cssFiles()) {
      const content = readFileSync(file, "utf8");
      const defined = definedVarNames(content);
      for (const m of content.matchAll(/var\((--[a-zA-Z0-9-]+)[),]/g)) {
        const name = m[1];
        expect(
          defined.has(name) || tokenVars.has(name) || injected.has(name),
          `${file} references undefined custom property ${name}`,
        ).toBe(true);
      }
    }
  });
});

describe("Mukta typography (#193)", () => {
  it("self-hosts Mukta via next/font with latin+devanagari and four weights", () => {
    expect(layoutTsx).toContain('from "next/font/google"');
    expect(layoutTsx).toMatch(/subsets:\s*\["devanagari", "latin"\]/);
    expect(layoutTsx).toMatch(/weight:\s*\["400", "500", "600", "700"\]/);
  });

  it("feeds --font-mukta into the blueprint fallback stack", () => {
    expect(layoutTsx).toContain('variable: "--font-mukta"');
    expect(tokensCss).toContain(
      'var(--font-mukta), "Noto Sans Devanagari", "Nirmala UI"',
    );
  });

  it("holds the 1.625 body floor and tight heading leading", () => {
    expect(globalsCss).toMatch(/line-height: 1\.625/);
    expect(globalsCss).toMatch(/line-height: 1\.25/);
  });
});

describe("reduced-motion kill switch (#193, story 33)", () => {
  it("kills animations and transitions under prefers-reduced-motion in base layer", () => {
    const baseBlock = globalsCss.slice(
      globalsCss.indexOf("@layer base"),
      globalsCss.lastIndexOf("}"),
    );
    expect(baseBlock).toMatch(/@media \(prefers-reduced-motion: reduce\)/);
    expect(baseBlock).toContain("animation-duration: 0.01ms !important");
    expect(baseBlock).toContain("animation-iteration-count: 1 !important");
    expect(baseBlock).toContain("transition-duration: 0.01ms !important");
  });
});

function colorLeaves(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (value && typeof value === "object")
    return Object.values(value).flatMap(colorLeaves);
  return [];
}
