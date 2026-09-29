import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// Indirection avoids Vite's static rewrite of `new URL("./x.css", import.meta.url)`,
// which would turn a literal CSS asset reference into a non-file URL.
const here = (rel: string) => new URL(rel, import.meta.url);

// #581: the handoff's progress bar is indeterminate, and jsdom applies no
// stylesheet, so a sliding segment and a plain div are indistinguishable in the
// rendered tree. This gate reads the sheet off disk for the same reason the
// design-token gate, the shared sign-in atoms' one-off-utility gate and the
// ring's CSS contract test do: the contract lives in the CSS, so the assertion
// reads the CSS. A `transition: width` here would reintroduce a bar that fills
// towards a known endpoint - the countdown's visual, without the countdown.
const css = readFileSync(here("./doneScreen.module.css"), "utf8");

describe("DoneScreen progress indicator animation", () => {
  it("slides the fill on a transform, so nothing implies a known duration", () => {
    const fill = css.match(/\.progressFill\s*\{[^}]*\}/)?.[0] ?? "";
    expect(fill).toMatch(/animation:\s*progressSlide/);

    const keyframes =
      css.match(/@keyframes\s+progressSlide\s*\{[\s\S]*?\n\}/)?.[0] ?? "";
    expect(keyframes).toMatch(/transform:\s*translateX/);
  });

  it("does not transition a width - that was the countdown's visual", () => {
    expect(css).not.toMatch(/transition:[^;]*\bwidth\b/);
    expect(css).not.toMatch(/animation:[^;]*\bwidth\b/);
  });

  it("adds no motion code of its own, and inherits the global floor", () => {
    // There is no per-component motion convention in this repository: zero
    // `motion-safe` / `motion-reduce` utilities, and one base-layer
    // `prefers-reduced-motion` block in globals.css that kills every
    // animation and transition app-wide. A keyframe animation in a component
    // module is covered by that floor for free, so a local duration override
    // here would be a second, weaker mechanism that only some of the animation
    // would answer to.
    expect(css).not.toMatch(/animation-duration/);
    expect(css).not.toMatch(/transition-duration/);
    // The floor itself is pinned by app/design-tokens.test.ts, which reads
    // globals.css. This file must not become a place that shadows it.
    expect(css).not.toMatch(/prefers-reduced-motion/);
  });
});
