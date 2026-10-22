// #709 C2b: the shared design-system chart component (components/ui/chart.tsx)
// - the ONE place this app touches recharts (plan-phase14-observability §9.2,
// docs/research/ui-component-library.md "Recommendation" + "Adoption steps":
// shadcn/ui chart primitive, adopted per feature, measured against NFR-003).
//
// What is worth pinning here is the contract the four Observability panels
// depend on: the config names each series' label and colour, the config is
// emitted as scoped `--color-<key>` custom properties, the container wraps
// recharts' ResponsiveContainer, and a payload item resolves back to its config
// entry so the tooltip and legend say the configured label rather than a
// dataKey.

import type React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { useChartDom } from "@/test/chartDom";

import {
  Bar,
  BarChart,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  ChartFigure,
  Line,
  LineChart,
  XAxis,
  YAxis,
} from "./chart";

const DATA = [
  { day: "2026-10-01", cost: 100, calls: 4 },
  { day: "2026-10-02", cost: 250, calls: 9 },
];

const CONFIG = {
  cost: { label: "Daily spend", color: "var(--accent)" },
  calls: { label: "Calls", color: "var(--warm)" },
};

beforeAll(() => useChartDom());

afterEach(() => cleanup());

describe("ChartContainer", () => {
  it("emits the config as scoped custom properties", () => {
    const { container } = render(
      <ChartContainer config={CONFIG} className="h-40">
        <BarChart data={DATA}>
          <Bar dataKey="cost" />
        </BarChart>
      </ChartContainer>,
    );

    const chart = container.querySelector("[data-chart]");
    expect(chart).toBeTruthy();
    const style = container.querySelector("style");
    expect(style?.innerHTML).toContain(
      `[data-chart=${chart?.getAttribute("data-chart")}]`,
    );
    expect(style?.innerHTML).toContain("--color-cost: var(--accent);");
    expect(style?.innerHTML).toContain("--color-calls: var(--warm);");
  });

  it("emits no style block when no series carries a colour", () => {
    const { container } = render(
      <ChartContainer config={{ cost: { label: "Daily spend" } }}>
        <BarChart data={DATA}>
          <Bar dataKey="cost" />
        </BarChart>
      </ChartContainer>,
    );

    expect(container.querySelector("style")).toBeNull();
  });

  it("scopes each chart's variables to its own id", () => {
    const { container } = render(
      <>
        <ChartContainer config={CONFIG}>
          <BarChart data={DATA}>
            <Bar dataKey="cost" />
          </BarChart>
        </ChartContainer>
        <ChartContainer
          config={{ other: { label: "Other", color: "var(--danger)" } }}
        >
          <BarChart data={DATA}>
            <Bar dataKey="cost" />
          </BarChart>
        </ChartContainer>
      </>,
    );

    const ids = [...container.querySelectorAll("[data-chart]")].map((node) =>
      node.getAttribute("data-chart"),
    );
    expect(ids[0]).toBeTruthy();
    expect(ids[0]).not.toBe(ids[1]);
  });

  it("actually draws the series it is handed", () => {
    const { container } = render(
      <ChartContainer config={CONFIG}>
        <BarChart data={DATA}>
          <Bar dataKey="cost" />
        </BarChart>
      </ChartContainer>,
    );

    expect(container.querySelector(".recharts-surface")).toBeTruthy();
    // Two data points, two rectangles. A zero-sized container draws nothing,
    // so this is the assertion that would catch the unmeasured-jsdom trap.
    expect(container.querySelectorAll(".recharts-bar-rectangle").length).toBe(
      2,
    );
  });

  it("passes arbitrary container props through", () => {
    render(
      <ChartContainer config={CONFIG} role="img" aria-label="AI spend trend">
        <BarChart data={DATA}>
          <Bar dataKey="cost" />
        </BarChart>
      </ChartContainer>,
    );

    const chart = screen.getByRole("img", { name: "AI spend trend" });
    expect(chart.getAttribute("data-chart")).toBeTruthy();
  });
});

describe("ChartTooltipContent", () => {
  /**
   * recharts 3 reads the hovered payload out of its own store, not off the
   * `<Tooltip>` props, so the tooltip is driven the way a real hover drives it:
   * a real chart with the tooltip pinned to a data point. Asserting against a
   * hand-passed `payload` would test the props, not the wiring.
   */
  function renderChartWithTooltip(content: React.ReactElement) {
    return render(
      <ChartContainer config={CONFIG}>
        <BarChart data={DATA}>
          <XAxis dataKey="day" />
          <YAxis />
          <Bar dataKey="cost" fill="var(--color-cost)" />
          <ChartTooltip defaultIndex={1} content={content} />
        </BarChart>
      </ChartContainer>,
    );
  }

  it("names the series from the config, not the dataKey", () => {
    renderChartWithTooltip(<ChartTooltipContent />);

    expect(screen.getByText("Daily spend")).toBeTruthy();
    expect(screen.getByText("250")).toBeTruthy();
  });

  it("runs a formatter over the value", () => {
    renderChartWithTooltip(
      <ChartTooltipContent formatter={(value) => `INR ${value}`} />,
    );

    expect(screen.getByText("INR 250")).toBeTruthy();
  });

  it("renders no body when no point is hovered", () => {
    const { container } = render(
      <ChartContainer config={CONFIG}>
        <BarChart data={DATA}>
          <Bar dataKey="cost" />
          <ChartTooltip content={<ChartTooltipContent />} />
        </BarChart>
      </ChartContainer>,
    );

    expect(container.textContent).not.toContain("Daily spend");
  });
});

describe("ChartLegendContent", () => {
  it("labels each legend entry from the config", () => {
    render(
      <ChartContainer config={CONFIG}>
        <BarChart data={DATA}>
          <Bar dataKey="cost" fill="var(--color-cost)" />
          <Bar dataKey="calls" fill="var(--color-calls)" />
          <ChartLegend content={<ChartLegendContent />} />
        </BarChart>
      </ChartContainer>,
    );

    expect(screen.getByText("Daily spend")).toBeTruthy();
    expect(screen.getByText("Calls")).toBeTruthy();
  });

  it("renders nothing when the chart declares no series", () => {
    const { container } = render(
      <ChartContainer config={CONFIG}>
        <BarChart data={DATA}>
          <ChartLegend content={<ChartLegendContent />} />
        </BarChart>
      </ChartContainer>,
    );

    expect(container.textContent).not.toContain("Daily spend");
  });
});

describe("ChartContainer reset styling", () => {
  it("keeps the recharts element reset with the design-system classes", () => {
    const { container } = render(
      <ChartContainer config={CONFIG}>
        <LineChart data={DATA}>
          <XAxis dataKey="day" />
          <YAxis />
          <Line dataKey="cost" />
        </LineChart>
      </ChartContainer>,
    );

    const chart = container.querySelector("[data-chart]") as HTMLElement;
    expect(chart.className).toContain("recharts-cartesian-axis-tick_text");
    expect(chart.className).toContain("fill-muted-foreground");
    expect(chart.className).toContain("recharts-surface");
  });
});

describe("ChartFigure accessibility", () => {
  const figure = (
    <ChartFigure
      config={CONFIG}
      testId="figure"
      ariaLabel="Daily spend over the window"
      description="1 Oct: 12 rupees; 2 Oct: 18 rupees"
    >
      <LineChart data={DATA}>
        <XAxis dataKey="day" />
        <YAxis />
        <Line dataKey="cost" />
      </LineChart>
    </ChartFigure>
  );

  /**
   * The load-bearing assertion. `role="img"` would also carry the aria-label
   * but tell assistive tech the subtree is one opaque graphic, which hides the
   * axis text and any legend under it - so the label would be the only
   * accessible content and every plotted value would be lost.
   */
  it("labels the region without collapsing its subtree into one image", () => {
    render(figure);

    const region = screen.getByTestId("figure");
    expect(region.getAttribute("role")).toBe("figure");
    expect(region.getAttribute("role")).not.toBe("img");
    expect(region.getAttribute("aria-label")).toBe(
      "Daily spend over the window",
    );
  });

  it("offers the plotted values as text, since the geometry cannot convey them", () => {
    render(figure);

    expect(screen.getByText("1 Oct: 12 rupees; 2 Oct: 18 rupees")).toBeTruthy();
  });

  it("omits the caption entirely when there is nothing to describe", () => {
    render(
      <ChartFigure config={CONFIG} testId="bare" ariaLabel="An empty chart">
        <LineChart data={DATA}>
          <XAxis dataKey="day" />
          <YAxis />
          <Line dataKey="cost" />
        </LineChart>
      </ChartFigure>,
    );

    expect(screen.getByTestId("bare").querySelector("figcaption")).toBeNull();
  });
});
