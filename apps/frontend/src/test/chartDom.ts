// #709 C2b: the jsdom stand-ins a recharts chart needs in order to actually
// draw, imported by the chart tests and by nothing else.
//
// recharts' `ResponsiveContainer` (which the shared `ChartContainer` wraps)
// measures its parent with `ResizeObserver` + `getBoundingClientRect`. jsdom
// implements neither: without these, the container measures 0x0, every chart
// renders nothing at all, and a test asserting "the chart drew" would pass
// against an empty div - the exact failure this ticket's chart-render
// assertions exist to catch.
//
// Scoped to the importing test file rather than put in vitest.setup.ts: the
// rest of the suite stubs `ResizeObserver` as a no-op for Radix poppers, and a
// globally-measuring environment would change what those tests are testing.
// Vitest isolates each file in its own jsdom, so nothing here leaks.

import { screen, waitFor } from "@testing-library/react";
import { expect, vi } from "vitest";

/** The box the chart itself is measured at. Any non-zero size renders. */
const CHART_WIDTH = 640;
const CHART_HEIGHT = 360;

/**
 * The box one element reports.
 *
 * Only recharts' responsive container gets the full plot size - that div is the
 * one it measures to size the chart. A blanket "every element is 640x360" is
 * the obvious shortcut and it is wrong: recharts reserves plot space by
 * measuring the legend, so a legend that also believes it is 360px tall eats
 * the whole chart and the bars silently vanish, which would make this harness
 * report a perfectly good chart as drawing nothing. Everything else reports a
 * zero-height line, which is what an unlaid-out element looks like in jsdom.
 */
function rectFor(this: Element): DOMRect {
  // recharts calls getBoundingClientRect() detached in at least one place, so
  // `this` can be undefined; treat that as "not the chart container".
  const isChart =
    this?.classList?.contains("recharts-responsive-container") ?? false;
  const width = CHART_WIDTH;
  const height = isChart ? CHART_HEIGHT : 0;
  return {
    width,
    height,
    top: 0,
    left: 0,
    bottom: height,
    right: width,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  } as DOMRect;
}

/**
 * Reports the first observation at a real size. recharts sets its state from
 * the observer's callback, so a stub that never fires leaves the chart
 * unmeasured - the callback fires synchronously from `observe` to match.
 */
class MeasuringResizeObserver implements ResizeObserver {
  private readonly targets = new Set<Element>();

  constructor(private readonly callback: ResizeObserverCallback) {}

  observe(target: Element) {
    this.targets.add(target);
    this.callback([entryFor(target)], this);
  }

  unobserve(target: Element) {
    this.targets.delete(target);
  }

  disconnect() {
    this.targets.clear();
  }
}

function entryFor(target: Element): ResizeObserverEntry {
  return {
    target,
    contentRect: target.getBoundingClientRect(),
    borderBoxSize: [],
    contentBoxSize: [],
    devicePixelContentBoxSize: [],
  } as unknown as ResizeObserverEntry;
}

/**
 * Make charts measurable for the rest of the current test file. Call once from
 * `beforeAll`, before any `render`.
 */
export function useChartDom() {
  window.ResizeObserver =
    MeasuringResizeObserver as unknown as typeof ResizeObserver;
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
    rectFor,
  );
  vi.spyOn(SVGElement.prototype, "getBoundingClientRect").mockImplementation(
    rectFor,
  );
}

/**
 * Wait for a chart to have drawn, then hand back its element.
 *
 * Waiting on the panel's `data-status="ready"` instead is a trap: the read
 * resolves and the panel reports ready a commit BEFORE recharts has measured
 * its container and drawn anything, so asserting a bar count there fails only
 * under load. This waits on the drawing itself, and returns the element so the
 * caller can assert the exact shape - which is stable, because recharts draws
 * a chart's whole series in one commit.
 */
export async function drawnChart(
  testId: string,
  drawnSelector = ".recharts-bar-rectangle",
): Promise<HTMLElement> {
  await waitFor(() => {
    expect(
      screen.getByTestId(testId).querySelectorAll(drawnSelector).length,
    ).toBeGreaterThan(0);
  });
  return screen.getByTestId(testId);
}
