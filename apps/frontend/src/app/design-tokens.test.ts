import { readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import tailwindConfig from "../../tailwind.config";

// Contract gates for PHASE-2.6 T02 (#193, FEAT-006): resolved brand tokens,
// Mukta typography, single palette source, reduced-motion kill switch.
// Extended by #564 with the class-attribute colour gate.

type ThemeToken = { path: string; value: string };

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

function tsFiles(): string[] {
  return sourceFiles((f) => /\.(ts|tsx)$/.test(f));
}

function cssFiles(): string[] {
  return sourceFiles((f) => f.endsWith(".css") && !f.endsWith("tokens.css"));
}

function allSourceFiles(): string[] {
  return sourceFiles((f) => /\.(css|tsx?)$/.test(f));
}

/** Repo-relative, posix-separated, so a finding names the file the brief does. */
function srcRelative(file: string): string {
  const root = fileURLToPath(here("../"));
  return relative(root, file).split(/[\\/]/).join("/");
}

function definedVarNames(content: string): Set<string> {
  const names = new Set<string>();
  for (const m of content.matchAll(/(--[a-zA-Z0-9-]+)\s*:/g)) names.add(m[1]);
  return names;
}

const themeExtend = tailwindConfig.theme?.extend ?? {};
const COLOUR_TOKENS = themeTokens(themeExtend.colors);
const COLOUR_TOKEN_PATHS = new Set(COLOUR_TOKENS.map((t) => t.path));
// Declared but not colour: elevation shadows and the radius scale. Kept as
// resolvable paths so the self-test can show they are real tokens the colour
// rule is not claiming (and would not have to invent a check for).
const SHADOW_TOKEN_PATHS = new Set(
  themeTokens(themeExtend.boxShadow).map((t) => t.path),
);
const RADIUS_TOKEN_PATHS = new Set(
  themeTokens(themeExtend.borderRadius).map((t) => t.path),
);
origin / main;

describe("resolved brand palette (#193)", () => {
  // The cases below walk the whole source tree with synchronous file reads, so
  // their runtime is a property of how many files the app has, not of what they
  // assert. Left on vitest's 5s default they flake: #623 caught one spending 8018ms
  // under full-suite CPU contention while passing in 3.2s alone, which reports as
  // a palette failure with no palette defect in it. The timeout is set well above
  // the observed worst case so a genuine regression still fails.
  const SCAN_TIMEOUT_MS = 60_000;

  it(
    "defines every resolved brand hex exactly once, in tokens.css",
    () => {
      for (const [role, hex] of Object.entries(BRAND_HEXES)) {
        expect(tokensCss, `missing ${role} ${hex}`).toContain(hex);
        expect(
          tokensCss.match(new RegExp(hex, "gi"))?.length ?? 0,
          `${hex} duplicated inside tokens.css`,
        ).toBe(1);
      }
      expect(tokensCss).toContain("--warn-soft: #fef3c7");
      expect(tokensCss).toContain("--warn-text: #92400e");
    },
    SCAN_TIMEOUT_MS,
  );

  it(
    "leaves the old seeded cyan accent nowhere in the app",
    () => {
      for (const file of allSourceFiles()) {
        const content = readFileSync(file, "utf8");
        for (const hex of SEEDED_CYAN_HEXES) {
          expect(content, `${file} still defines ${hex}`).not.toContain(hex);
        }
      }
    },
    SCAN_TIMEOUT_MS,
  );
});

describe("single palette source (#193)", () => {
  it("tailwind config consumes CSS variables, never hexes", () => {
    const leaves = COLOUR_TOKENS.map((t) => t.value);
    expect(leaves.length).toBeGreaterThan(0);
    for (const value of leaves) {
      // hsl(var(--x)) is the shadcn/ui slot form (#195): the var holds H S% L%
      // channels so Tailwind can inject alpha (hover:bg-primary/90); still a
      // tokens.css variable, so still single-source.
      const isVar =
        value.startsWith("var(--") ||
        /^hsl\(var\(--[a-z0-9-]+\)\)$/.test(value);
      expect(isVar, `non-var token: ${value}`).toBe(true);
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

// ---------------------------------------------------------------------------
// Class-attribute colour gate (#564, blueprint §1.2 Palette)
// ---------------------------------------------------------------------------
// Blueprint §1.2 Palette, the closing clause of its direction paragraph:
// "All colors keep the existing token vocabulary in
// apps/frontend/tailwind.config.ts; component code references token names
// only." That vocabulary is theme.extend.colors, and the config declares
// extend.colors alone, so no stock Tailwind palette step is part of it. This
// gate reads every class list in src and resolves every colour utility against
// that vocabulary, so a component cannot name a colour the design system does
// not define: no utility is emitted, and the text falls back to the browser
// default against whatever surface is behind it.
//
// STRICTNESS IS THE POINT. The defect that motivated the gate, `text-on-txt`,
// ends in a segment (`txt`) that IS a real token, so a leaf- or prefix-matching
// resolver passes the exact bug the gate exists to catch - as it would
// `warm-text` (-> success.text), `txt-strong` (-> accent.strong) and
// `on-surface` (-> surface). Resolution here therefore walks the colour tree
// path by path: an unknown final segment fails even when its trailing segment
// alone is known. The self-test below plants that shape on purpose so the
// failure mode stays demonstrable on demand.
//
// The rule is deliberately `text-`-scoped. Widening it to `bg-` / `border-` is
// a real decision - stock `border-b` against the real `border` colour alias,
// `bg-page` against `bg-page-bg` - and is not this gate's to make.

const COLOUR_PREFIX = "text";
/** Variant prefixes, then Tailwind's `!` important marker. Bracket variants are
 *  live in this tree (data-[...] x44, min-[...] x32, max-[...] x10), so a
 *  prefix pattern that stopped at the first alphanumeric would let
 *  `data-[disabled]:text-on-txt` through unchecked. */
const VARIANT_PREFIX = /^(?:[!]|(?:[^:\s[\]]|\[[^\]]*\])+:)+/;
const ALPHA_MODIFIER = /\/(?:\d{1,3}|\[[^\]]*\])$/;

/** Blueprint §1.3 Typography: the legal `text-*` size steps. An argument
 *  outside this set, and outside NON_COLOUR_TEXT, is read as a colour name. */
const FONT_SIZE_STEPS = new Set([
  "xs",
  "sm",
  "base",
  "lg",
  "xl",
  "2xl",
  "3xl",
  "4xl",
  "5xl",
]);

/** Tailwind's `text-` prefix is overloaded beyond colour and §1.2 governs
 *  colour only. Text alignment alone is 53 live sites (text-center 24,
 *  text-left 17, text-right 12). None of these name a colour. `inherit`,
 *  `current` and `transparent` are self-referential CSS-wide values, not
 *  palette entries and not tokens. */
const NON_COLOUR_TEXT = new Set([
  "left",
  "center",
  "right",
  "justify",
  "justify-all",
  "start",
  "end",
  "wrap",
  "nowrap",
  "balance",
  "pretty",
  "ellipsis",
  "clip",
  "underline",
  "overline",
  "line-through",
  "no-underline",
  "uppercase",
  "lowercase",
  "capitalize",
  "normal-case",
  "indent",
  "inherit",
  "current",
  "transparent",
]);
/** text-opacity-* and text-shadow-* are the two remaining overloaded families. */
const NON_COLOUR_TEXT_ARGUMENT = /^(?:opacity|shadow)-[a-z0-9-]+$/;

/** `text-[...]` is a rejection case, not a resolution case. The one live
 *  exception is a length, which is a font size the tree writes arbitrarily in
 *  dozens of places (text-[10px], text-[0.6875rem], ...). Anything else in
 *  brackets - a hex, a colour function, a var(), a theme() call - is a colour
 *  smuggled past the token vocabulary, and is rejected. */
const ARBITRARY_VALUE = /^\[.+\]$/;
const ARBITRARY_LENGTH =
  /^-?(?:\d*\.?\d+)(?:px|rem|em|%|pt|vh|vw|vmin|vmax|ch|ex)?$/;

/** Tailwind v3's default palette. This project declares theme.extend.colors
 *  only, so no stock step is a token name: the §1.2 "Tailwind ref" column
 *  records which step each token was picked from, it does not authorise naming
 *  the step directly. */
const STOCK_PALETTE = new Set([
  "slate",
  "gray",
  "zinc",
  "neutral",
  "stone",
  "red",
  "orange",
  "amber",
  "yellow",
  "lime",
  "green",
  "emerald",
  "teal",
  "cyan",
  "sky",
  "blue",
  "indigo",
  "violet",
  "purple",
  "fuchsia",
  "pink",
  "rose",
  "black",
  "white",
]);

/** The three findings, as templates, so the self-test asserts the shipped
 *  strings instead of re-spelling them. */
const UNRESOLVED = (utility: string, name: string) =>
  `${utility}: "${name}" is not a resolved design token (full-path match only)`;
const STOCK_ENTRY = (utility: string, name: string) =>
  `${utility}: ${name} is a framework-default palette entry, not a design token`;
const INLINE_COLOUR = (utility: string, value: string) =>
  `${utility}: ${value} is an arbitrary inline colour, not a design token`;

/** The checker the live rule and the self-test both call. Pure: no file I/O,
 *  so deliberately broken input can be fed through the same code path. Each
 *  finding names the utility, the token name it asked for, and why that name
 *  does not resolve. */
function classLiteralProblems(literal: string): string[] {
  return literal.split(/\s+/).flatMap(colourUtilityProblems);
}

function colourUtilityProblems(token: string): string[] {
  const core = token.replace(VARIANT_PREFIX, "");
  if (!core.startsWith(`${COLOUR_PREFIX}-`)) return [];
  const argument = core.slice(COLOUR_PREFIX.length + 1);
  if (FONT_SIZE_STEPS.has(argument)) return [];
  if (
    NON_COLOUR_TEXT.has(argument) ||
    NON_COLOUR_TEXT_ARGUMENT.test(argument)
  ) {
    return [];
  }
  const name = argument.replace(ALPHA_MODIFIER, "");
  if (ARBITRARY_VALUE.test(name)) {
    // A bare length is a font size the tree writes arbitrarily; anything else
    // in brackets is a colour that bypassed the token vocabulary.
    return ARBITRARY_LENGTH.test(name.slice(1, -1))
      ? []
      : [INLINE_COLOUR(token, name)];
  }
  // Token resolution first: if the palette ever grows an `amber`, text-amber is
  // a token and must not be reported as a stock palette entry.
  if (COLOUR_TOKEN_PATHS.has(name)) return [];
  if (STOCK_PALETTE.has(name.split("-")[0]!)) {
    return [STOCK_ENTRY(token, name)];
  }
  return [UNRESOLVED(token, name)];
}

/** One class list found in a source file, and the line it starts on. */
type ClassLiteral = { text: string; line: number };

const JSX_CLASS_ATTRIBUTES = new Set(["className", "class"]);
/** The test-naming callees this repo actually uses (it 1258, describe 311,
 *  afterEach 81, beforeEach 56, beforeAll 17). A description is prose. */
const TEST_NAME_CALLEES = new Set([
  "it",
  "test",
  "describe",
  "beforeEach",
  "afterEach",
  "beforeAll",
]);

function lineIndex(source: string): number[] {
  const starts = [0];
  for (let i = 0; i < source.length; i++) {
    if (source[i] === "\n") starts.push(i + 1);
  }
  return starts;
}

function lineAt(starts: number[], at: number): number {
  let lo = 0;
  let hi = starts.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (starts[mid]! <= at) lo = mid;
    else hi = mid - 1;
  }
  return lo + 1;
}

/** Index just past the closing quote of the literal opened at `start`. */
function literalClose(source: string, start: number, quote: string): number {
  let i = start + 1;
  while (i < source.length) {
    if (source[i] === "\\") i += 2;
    else if (source[i] === quote) return i + 1;
    else i++;
  }
  return source.length;
}

/** Index of the `}` closing the `{` at `open`, skipping nested literals. */
function braceClose(source: string, open: number): number {
  let depth = 0;
  for (let i = open; i < source.length; i++) {
    const ch = source[i]!;
    if (ch === "{") depth++;
    else if (ch === "}" && --depth === 0) return i;
    else if (ch === '"' || ch === "'" || ch === "`") {
      i = literalClose(source, i, ch) - 1;
    }
  }
  return source.length;
}

/** Walk back from a quote to the identifier assigned to immediately before it,
 *  and whether the walk reached a JSX tag open without leaving the tag. */
function attributeBefore(
  source: string,
  quoteAt: number,
): { attribute: string | null; inJsxTag: boolean } {
  let attribute: string | null = null;
  let i = quoteAt - 1;
  for (;;) {
    while (i >= 0 && /\s/.test(source[i]!)) i--;
    if (i < 0) return { attribute, inJsxTag: false };
    const ch = source[i]!;
    if (ch === "<") return { attribute, inJsxTag: true };
    if (ch === "=") {
      const end = i;
      let start = end;
      while (--start >= 0 && /\s/.test(source[start]!));
      while (start > 0 && /[A-Za-z0-9_$:-]/.test(source[start - 1]!)) start--;
      if (start === end) return { attribute, inJsxTag: false };
      attribute = source.slice(start, end);
      i = start - 1;
      continue;
    }
    if (/[A-Za-z0-9_$]/.test(ch)) {
      while (i >= 0 && /[A-Za-z0-9_$]/.test(source[i]!)) i--;
      continue;
    }
    return { attribute, inJsxTag: false };
  }
}

/** True when the quote opens the first argument of `it(...)` / `describe(...)`
 *  and friends, i.e. a test name rather than a class list. */
function isTestNameLiteral(source: string, quoteAt: number): boolean {
  let i = quoteAt - 1;
  while (i >= 0 && /\s/.test(source[i]!)) i--;
  if (source[i] !== "(") return false;
  const chain: string[] = [];
  for (;;) {
    i--;
    while (i >= 0 && /\s/.test(source[i]!)) i--;
    const end = i + 1;
    while (i >= 0 && /[A-Za-z0-9_$]/.test(source[i]!)) i--;
    if (end === i + 1) break;
    chain.push(source.slice(i + 1, end));
    while (i >= 0 && /\s/.test(source[i]!)) i--;
    if (source[i] !== ".") break;
  }
  const callee = chain[chain.length - 1];
  return callee !== undefined && TEST_NAME_CALLEES.has(callee);
}

/** Whether a quoted literal should be read as a class list. Default yes: a
 *  blind spot is worse for a gate than a false positive, and the four shapes
 *  classes arrive in (className attribute, cn() composition, cva variant
 *  string, module-level Record<string, string> map) share no single syntax.
 *  The three exclusions are the literals that are never class lists. */
function isClassCarrier(source: string, quoteAt: number): boolean {
  if (isTestNameLiteral(source, quoteAt)) return false;
  const { attribute, inJsxTag } = attributeBefore(source, quoteAt);
  if (attribute === null) return true;
  if (attribute.startsWith("data-") || attribute.startsWith("aria-")) {
    return false;
  }
  return !(inJsxTag && !JSX_CLASS_ATTRIBUTES.has(attribute));
}

/** Every class list in a source file, with its line. Comments are skipped, so
 *  the shadcn primitives' `bg-accent/text-accent-foreground` prose about a
 *  deviation is never read as a class. */
function classLiterals(source: string): ClassLiteral[] {
  const starts = lineIndex(source);
  const found: ClassLiteral[] = [];
  const emit = (from: number, to: number) => {
    if (to > from) {
      found.push({ text: source.slice(from, to), line: lineAt(starts, from) });
    }
  };

  // Recurses into `${...}` so a ternary's strings are read as their own
  // literals rather than as one run-on template.
  const scan = (from: number, to: number): void => {
    let i = from;
    while (i < to) {
      const ch = source[i]!;
      if (ch === "/" && source[i + 1] === "/") {
        const newline = source.indexOf("\n", i);
        i = newline === -1 || newline > to ? to : newline;
      } else if (ch === "/" && source[i + 1] === "*") {
        const stop = source.indexOf("*/", i + 2);
        i = stop === -1 ? to : Math.min(stop + 2, to);
      } else if (ch === '"' || ch === "'") {
        const end = Math.min(literalClose(source, i, ch), to);
        if (isClassCarrier(source, i)) emit(i + 1, Math.max(i + 1, end - 1));
        i = end;
      } else if (ch === "`") {
        i = scanTemplate(source, i, to, emit, scan);
      } else {
        i++;
      }
    }
  };
  scan(0, source.length);
  return found;
}

type Emit = (from: number, to: number) => void;
type Scan = (from: number, to: number) => void;

/** A template literal contributes its literal chunks; each `${...}` is handed
 *  back to the caller to scan. Returns the index just past the closing tick. */
function scanTemplate(
  source: string,
  start: number,
  to: number,
  emit: Emit,
  scan: Scan,
): number {
  let chunk = start + 1;
  let i = chunk;
  while (i < to) {
    if (source[i] === "\\") {
      i += 2;
    } else if (source[i] === "`") {
      emit(chunk, i);
      return i + 1;
    } else if (source[i] === "$" && source[i + 1] === "{") {
      emit(chunk, i);
      const close = Math.min(braceClose(source, i + 1), to);
      scan(i + 2, Math.max(i + 2, close));
      i = close + 1;
      chunk = i;
    } else {
      i++;
    }
  }
  return i;
}

/** One finding per unresolved colour utility, prefixed with file:line. The live
 *  rule and the self-test both go through this, so the self-test exercises the
 *  shipped detector rather than a parallel reimplementation. */
function colourUtilityFindings(file: string, source: string): string[] {
  return classLiterals(source).flatMap((literal) =>
    classLiteralProblems(literal.text).map(
      (problem) => `${file}:${literal.line}: ${problem}`,
    ),
  );
}

describe("class-attribute colour utilities (#564, ui-blueprint §1.2)", () => {
  const tree = () =>
    tsFiles().map((file) => ({
      file: srcRelative(file),
      source: readFileSync(file, "utf8"),
    }));

  it("resolves every colour utility named in a class list to a design token", () => {
    const files = tree();
    expect(
      files.flatMap((f) => colourUtilityFindings(f.file, f.source)),
    ).toEqual([]);
    // A scope change that stopped reading the tree would leave the rule green
    // for the wrong reason, so the coverage is asserted, not assumed.
    expect(files.length).toBeGreaterThan(100);
    expect(
      files.reduce((n, f) => n + classLiterals(f.source).length, 0),
    ).toBeGreaterThan(2000);
  });

  it("reads the live tree's own colour vocabulary, not only the planted cases", () => {
    let utilities = 0;
    for (const { source } of tree()) {
      for (const literal of classLiterals(source)) {
        for (const token of literal.text.split(/\s+/)) {
          if (token.startsWith(`${COLOUR_PREFIX}-`)) utilities++;
        }
      }
    }
    // The tree carries 233 text-txt sites on its own, so a resolver that
    // rejected live tokens could not sit at zero here.
    expect(utilities).toBeGreaterThan(500);
  });
});

describe("class colour-utility detector self-test (#564 red/green proof)", () => {
  // Same checker the live rule calls, fed deliberately broken input, asserting
  // the exact finding. A detector with no self-test can be green for the wrong
  // reason - suffix matching, over-broad scope, or a scope so narrow it reads
  // nothing - and each of those is covered by a case below, the last of them by
  // the coverage assertions in the live rule above.

  it("rejects a planted token that only shares a trailing segment with a real one", () => {
    // The reported defect's exact shape. `txt` is a real token (txt.DEFAULT)
    // and `on-txt` is not, so a leaf- or prefix-matching resolver passes the
    // one bug this gate exists to catch.
    expect(colourUtilityProblems("text-on-txt")).toEqual([
      UNRESOLVED("text-on-txt", "on-txt"),
    ]);
    // The other three orphans have the same shape, each ending in a real token.
    expect(colourUtilityProblems("text-warm-text")).toEqual([
      UNRESOLVED("text-warm-text", "warm-text"),
    ]);
    expect(colourUtilityProblems("text-txt-strong")).toEqual([
      UNRESOLVED("text-txt-strong", "txt-strong"),
    ]);
    expect(colourUtilityProblems("text-on-surface")).toEqual([
      UNRESOLVED("text-on-surface", "on-surface"),
    ]);
    // Those trailing segments are real, which is exactly what makes a suffix
    // match blind rather than merely imprecise.
    for (const token of [
      "text-txt",
      "text-surface",
      "text-success-text",
      "text-accent-strong",
    ]) {
      expect(colourUtilityProblems(token)).toEqual([]);
    }
    // Variants and alpha modifiers do not hide the argument.
    expect(colourUtilityProblems("hover:text-on-txt/90")).toEqual([
      UNRESOLVED("hover:text-on-txt/90", "on-txt"),
    ]);
  });

  it("resolves the colour vocabulary by full path, never by leaf", () => {
    for (const path of [
      "accent-strong",
      "page-bg",
      "txt",
      "txt-sub",
      "on-accent",
    ]) {
      expect(COLOUR_TOKEN_PATHS.has(path)).toBe(true);
    }
    // A DEFAULT key contributes no segment: txt.DEFAULT is the class text-txt.
    expect(COLOUR_TOKEN_PATHS.has("")).toBe(false);
    // The trailing segments the four orphans borrow, and the orphans themselves.
    for (const name of ["txt", "surface", "success-text", "accent-strong"]) {
      expect(COLOUR_TOKEN_PATHS.has(name)).toBe(true);
    }
    for (const name of ["on-txt", "on-surface", "warm-text", "txt-strong"]) {
      expect(COLOUR_TOKEN_PATHS.has(name)).toBe(false);
    }
  });

  it("rejects a framework-default palette entry and an arbitrary inline colour", () => {
    // The stock palette is not the declared vocabulary: the config declares
    // theme.extend.colors only, so no stock step is a token name.
    expect(colourUtilityProblems("text-slate-500")).toEqual([
      STOCK_ENTRY("text-slate-500", "slate-500"),
    ]);
    for (const utility of [
      "text-red-600",
      "text-teal-700",
      "text-black",
      "text-white",
    ]) {
      expect(colourUtilityProblems(utility)).toHaveLength(1);
    }
    // A hex, a colour function, and a var() or theme() call are all a colour
    // smuggled past the token vocabulary.
    expect(colourUtilityProblems("text-[#fff]")).toEqual([
      INLINE_COLOUR("text-[#fff]", "[#fff]"),
    ]);
    for (const utility of [
      "text-[rgb(0,0,0)]",
      "text-[hsl(0_0%_0%)]",
      "text-[var(--brand-ink)]",
      "text-[theme(colors.brand.ink)]",
    ]) {
      expect(colourUtilityProblems(utility)).toEqual([
        INLINE_COLOUR(utility, utility.slice(COLOUR_PREFIX.length + 1)),
      ]);
    }
    // A length argument is a font size the tree writes arbitrarily, not a colour.
    expect(colourUtilityProblems("text-[10px]")).toEqual([]);
    expect(colourUtilityProblems("text-[0.6875rem]")).toEqual([]);
  });

  it("sees a colour utility behind any variant prefix", () => {
    // Bracket variants are live (data-[...] x44, min-[...] x32, max-[...] x10)
    // and Tailwind's `!` marker can precede one, so a prefix pattern that stops
    // at the first alphanumeric would let these through unchecked.
    for (const utility of [
      "hover:text-on-txt",
      "focus-visible:text-on-txt",
      "data-[disabled]:text-on-txt",
      "min-[720px]:text-on-txt",
      "dark:data-[state=open]:text-on-txt",
      "!text-on-txt",
    ]) {
      expect(colourUtilityProblems(utility)).toEqual([
        UNRESOLVED(utility, "on-txt"),
      ]);
    }
  });

  it("does not fire on the overloaded non-colour text- utilities", () => {
    // 53 live alignment sites (text-center 24, text-left 17, text-right 12).
    expect(
      classLiteralProblems(
        "text-left text-center text-right text-justify text-start text-end",
      ),
    ).toEqual([]);
    // The blueprint §1.3 size steps, and the remaining non-colour families.
    expect(classLiteralProblems("text-xs text-sm text-base text-5xl")).toEqual(
      [],
    );
    expect(classLiteralProblems("text-ellipsis text-clip")).toEqual([]);
    expect(
      classLiteralProblems(
        "text-underline text-line-through text-no-underline",
      ),
    ).toEqual([]);
    expect(
      classLiteralProblems("text-uppercase text-lowercase text-normal-case"),
    ).toEqual([]);
    expect(classLiteralProblems("text-opacity-50 text-shadow-sm")).toEqual([]);
    // Self-referential CSS-wide values name no token and no palette step.
    expect(colourUtilityProblems("text-inherit")).toEqual([]);
  });

  it("does not claim the non-colour token namespaces", () => {
    // Elevation and radius come from other theme namespaces. `border`, `input`
    // and `ring` are real colour aliases, so blanket-excluding those prefixes to
    // dodge stock `border-b` would break the rule in the other direction.
    for (const path of ["card", "pop"]) {
      expect(SHADOW_TOKEN_PATHS.has(path)).toBe(true);
    }
    for (const path of ["sm", "lg"]) {
      expect(RADIUS_TOKEN_PATHS.has(path)).toBe(true);
    }
    // `md` and `full` are the stock radius scale, not project tokens.
    for (const path of ["md", "full"]) {
      expect(RADIUS_TOKEN_PATHS.has(path)).toBe(false);
    }
    expect(
      classLiteralProblems(
        "shadow-card shadow-pop rounded-sm rounded-md rounded-lg rounded-full rounded-l-md rounded-t-lg ring-accent-soft ring-offset-background border-input",
      ),
    ).toEqual([]);
  });

  it("matches a utility argument whole, so a prefix of a real token cannot shadow it", () => {
    // bg-page is a prefix of the legitimate bg-page-bg (page.bg); inside the
    // rule's scope the same shape is text-page against text-page-bg, and
    // `page` has only page.bg, so the shadowed side is the defect.
    expect(colourUtilityProblems("text-page-bg")).toEqual([]);
    expect(colourUtilityProblems("text-page")).toEqual([
      UNRESOLVED("text-page", "page"),
    ]);
    expect(colourUtilityProblems("bg-page-bg")).toEqual([]);
  });

  it("ignores the class-shaped token that exists only in a shadcn comment", () => {
    // ui/button.tsx and ui/dropdown-menu.tsx both mention
    // bg-accent/text-accent-foreground in prose about a deviation.
    // accent.foreground is not in the tree, so a file-wide grep flags them and
    // invites "fixing" comments that document a decision.
    expect(
      colourUtilityFindings(
        "planted.tsx",
        [
          "// Token bridge: ghost/outline hover uses accent-soft/accent-strong",
          "// instead of upstream bg-accent/text-accent-foreground, because the",
          "// app's `accent` theme group is the solid brand teal.",
          "/* text-accent-foreground and text-bearing are prose here too. */",
        ].join("\n"),
      ),
    ).toEqual([]);
  });

  it("reads class maps, cva variants and class ternaries, not just className", () => {
    expect(
      colourUtilityFindings(
        "planted.tsx",
        [
          "const TONE: Record<string, string> = {",
          '  below: "bg-warm-soft text-warm-text",',
          "};",
          "const variants = cva(",
          '  "rounded-md text-sm",',
          "  {",
          "    variants: {",
          '      danger: "bg-danger text-on-txt",',
          "    },",
          "  },",
          ");",
          "const pick = (on: boolean) =>",
          '  `text-sm ${on ? "bg-surface text-txt-strong" : "text-txt-sub"}`;',
          'const classes = "mb-4 text-sm text-on-surface";',
          'const el = <p className={cn("text-sm", tone && "text-on-txt")} />;',
        ].join("\n"),
      ),
    ).toEqual([
      `planted.tsx:2: ${UNRESOLVED("text-warm-text", "warm-text")}`,
      `planted.tsx:8: ${UNRESOLVED("text-on-txt", "on-txt")}`,
      `planted.tsx:13: ${UNRESOLVED("text-txt-strong", "txt-strong")}`,
      `planted.tsx:14: ${UNRESOLVED("text-on-surface", "on-surface")}`,
      `planted.tsx:15: ${UNRESOLVED("text-on-txt", "on-txt")}`,
    ]);
  });

  it("does not read a non-class attribute or a test description as a class list", () => {
    expect(
      colourUtilityFindings(
        "planted.tsx",
        'const el = <div data-testid="text-form" aria-label="text-only mode" />;',
      ),
    ).toEqual([]);
    expect(
      colourUtilityFindings(
        "planted.test.tsx",
        'it("sends text-only intake without any note", async () => {});',
      ),
    ).toEqual([]);
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

describe("shadcn/ui slot bridge (#195)", () => {
  // Each triplet restates a resolved hex token above (see the bridge block in
  // tokens.css); this gate fails when one side moves without the other.
  // One channel-step of slack absorbs the rounding used when writing HSL.
  const BRIDGE_SLOTS: Record<string, { source: string; hex: string }> = {
    "--ui-primary": { source: "--accent", hex: "#0f766e" },
    "--ui-primary-fg": { source: "--on-accent", hex: "#ffffff" },
    "--ui-secondary": { source: "--warm-soft", hex: "#fff7ed" },
    "--ui-secondary-fg": { source: "--warm", hex: "#c2410c" },
    "--ui-destructive": { source: "--danger", hex: "#b91c1c" },
    "--ui-destructive-fg": { source: "--on-accent", hex: "#ffffff" },
  };

  it("keeps every alpha-capable triplet in sync with its source token", () => {
    for (const [name, { source, hex }] of Object.entries(BRIDGE_SLOTS)) {
      const m = tokensCss.match(
        new RegExp(`${name}:\\s*([\\d.]+)\\s+([\\d.]+)%\\s+([\\d.]+)%`),
      );
      expect(m, `${name} missing from tokens.css bridge`).not.toBeNull();
      const [h, s, l] = [
        Number(m![1]),
        Number(m![2]) / 100,
        Number(m![3]) / 100,
      ];

      const expected = hexToRgb(hex);
      const actual = hslToRgb(h, s, l);
      for (const channel of ["r", "g", "b"] as const) {
        expect(
          Math.abs(actual[channel] - expected[channel]),
          `${name} (${source}) drifted from ${hex}`,
        ).toBeLessThanOrEqual(1);
      }
      // The source token itself must exist exactly where #193 says it does.
      expect(tokensCss).toContain(`${source}: ${hex}`);
    }
  });
});

/** Path-preserving walk of one theme namespace. `accent.strong` becomes the
 *  path "accent-strong", a nested `page.bg` becomes "page-bg", and a `DEFAULT`
 *  key contributes no segment ("txt.DEFAULT" is the class "text-txt"). A
 *  single walk serves both consumers here: the values feed the var() rule, the
 *  paths feed class-utility resolution. Never match on a suffix of a path -
 *  see the class gate below. */
function themeTokens(node: unknown, prefix: string[] = []): ThemeToken[] {
  if (typeof node === "string")
    return [{ path: prefix.join("-"), value: node }];
  if (node && typeof node === "object") {
    return Object.entries(node as Record<string, unknown>).flatMap(
      ([key, child]) =>
        themeTokens(child, key === "DEFAULT" ? prefix : [...prefix, key]),
    );
  }
  return [];
}

function hexToRgb(hex: string): { r: number; g: number; b: number } {
  const v = parseInt(hex.slice(1), 16);
  return { r: (v >> 16) & 255, g: (v >> 8) & 255, b: v & 255 };
}

function hslToRgb(
  h: number,
  s: number,
  l: number,
): { r: number; g: number; b: number } {
  const k = (n: number) => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (n: number) => {
    const c = l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
    return Math.round(255 * c);
  };
  return { r: f(0), g: f(8), b: f(4) };
}
