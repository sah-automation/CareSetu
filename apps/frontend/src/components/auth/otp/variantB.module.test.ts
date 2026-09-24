import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// Indirection avoids Vite's static rewrite of `new URL("./x.css", import.meta.url)`,
// which would turn a literal CSS asset reference into a non-file URL.
const here = (rel: string) => new URL(rel, import.meta.url);
const css = readFileSync(here("./variantB.module.css"), "utf8");

// Contract gate for the countdown wheel centering regression: CountdownRing
// renders a 72x72 SVG inside a 5rem (.ring) container, with the timer text
// (.ringTime) absolutely positioned inset:0 and flex-centered. The wheel and
// the text share the same center only when the SVG scales to fill the ring;
// before that rule the SVG stayed 72px top-left inside the 80px box, sitting
// the countdown ~4px right/down of the wheel's center.

describe("CountdownRing wheel centering", () => {
  it("scales the ring SVG to fill its container", () => {
    expect(css).toMatch(/\.ring\s+svg\s*\{/);
    const rule = css.match(/\.ring\s+svg\s*\{[^}]*\}/)?.[0] ?? "";
    expect(rule).toMatch(/width:\s*100%/);
    expect(rule).toMatch(/height:\s*100%/);
  });

  it("keeps a sane 5rem ring radius so the scale is uniform", () => {
    const ring = css.match(/\.ring\s*\{[^}]*\}/)?.[0] ?? "";
    expect(ring).toMatch(/width:\s*5rem/);
    expect(ring).toMatch(/height:\s*5rem/);
  });
});
