"use client";

// #709 C2b: the app's ONE chart primitive - the shadcn/ui `chart` component
// (new-york style, same registry `card`/`badge`/`skeleton` came from per
// #195/#600) over recharts, adopted per the design-library research
// (docs/research/ui-component-library.md): the operator Observability panels
// draw cost/usage/quality/latency as charts, and a hand-rolled SVG per panel is
// exactly the copy-paste drift that research rejected.
//
// Token bridge (#193/#195). Upstream's chart is token-agnostic in a way this app
// is not, so three edits:
//   * `THEMES` collapses to light-only. Upstream emits a second block for a
//     `.dark` scope; this app ships one light surface (src/app/tokens.css), and
//     a dead `.dark` selector would be a theme that no deployment has.
//   * Upstream's `bg-background` / `border-border` / `fill-muted-foreground`
//     in the tooltip and the recharts reset block resolve through the shadcn
//     slots, which DO exist here (tailwind.config.ts maps background/border/
//     muted) - kept as-is so the tooltip floats on the same surface tokens the
//     rest of the shell uses.
//   * `--color-<key>` values are NOT declared here. A panel's ChartConfig names
//     this app's own tokens (`var(--accent)`, `var(--warm)`, ...), so the
//     palette still has the single source the #193 token gate counts and no hex
//     is repeated inside a component.
//
// Weight (research guardrail 4, NFR-003): recharts is the one new client-side
// runtime dependency in this change. It is reached only from the operator
// Observability panel routes, never from the patient/partner/doctor shells, and
// `npm run check:pages` measures those four panel routes against the 1.5 MB
// gate (the recharts chunk is code-split per route, so `/operator` alone does
// not carry it). Panels must import from HERE, never `recharts` directly - a
// direct import is how two panels end up with two palettes. The recharts
// primitives panels need are therefore re-exported below; that re-export is the
// boundary, not a leak through it.

import * as React from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Line,
  LineChart,
  XAxis,
  YAxis,
} from "recharts";
import type { DefaultLegendContentProps, TooltipContentProps } from "recharts";
import * as RechartsPrimitive from "recharts";

import { cn } from "@/lib/utils";

// { THEME_NAME: CSS_SELECTOR }. Light-only: see the token bridge above.
const THEMES = { light: "" } as const;

/**
 * What one series in a chart is called and which colour it wears. Exactly one of
 * `color` / `theme` may be set: a config that carried both would have two
 * sources for one series and the tooltip could name a colour the bars never
 * painted.
 */
export type ChartConfig = {
  [k in string]: {
    label?: React.ReactNode;
    icon?: React.ComponentType;
  } & (
    | { color?: string; theme?: never }
    | { color?: never; theme: Record<keyof typeof THEMES, string> }
  );
};

type ChartContextProps = {
  config: ChartConfig;
};

const ChartContext = React.createContext<ChartContextProps | null>(null);

function useChart() {
  const context = React.useContext(ChartContext);

  if (!context) {
    throw new Error("useChart must be used within a <ChartContainer />");
  }

  return context;
}

/**
 * The chart surface: a token-styled `div` wrapping recharts' `ResponsiveContainer`,
 * carrying the config every descendant reads for its labels and colours.
 * Panels put their axes/series inside; the responsive sizing and the
 * `recharts-*` reset styling stay here so no panel restates them.
 */
const ChartContainer = React.forwardRef<
  HTMLDivElement,
  React.ComponentProps<"div"> & {
    config: ChartConfig;
    children: React.ComponentProps<
      typeof RechartsPrimitive.ResponsiveContainer
    >["children"];
  }
>(({ id, className, children, config, ...props }, ref) => {
  const uniqueId = React.useId();
  const chartId = `chart-${id || uniqueId.replace(/:/g, "")}`;

  return (
    <ChartContext.Provider value={{ config }}>
      <div
        data-chart={chartId}
        ref={ref}
        className={cn(
          "flex aspect-video justify-center text-xs [&_.recharts-cartesian-axis-tick_text]:fill-muted-foreground [&_.recharts-cartesian-grid_line[stroke='#ccc']]:stroke-border/50 [&_.recharts-curve.recharts-tooltip-cursor]:stroke-border [&_.recharts-dot[stroke='#fff']]:stroke-transparent [&_.recharts-layer]:outline-none [&_.recharts-polar-grid_[stroke='#ccc']]:stroke-border [&_.recharts-radial-bar-background-sector]:fill-muted [&_.recharts-rectangle.recharts-tooltip-cursor]:fill-muted [&_.recharts-reference-line_[stroke='#ccc']]:stroke-border [&_.recharts-sector[stroke='#fff']]:stroke-transparent [&_.recharts-sector]:outline-none [&_.recharts-surface]:outline-none",
          className,
        )}
        {...props}
      >
        <ChartStyle id={chartId} config={config} />
        <RechartsPrimitive.ResponsiveContainer>
          {children}
        </RechartsPrimitive.ResponsiveContainer>
      </div>
    </ChartContext.Provider>
  );
});
ChartContainer.displayName = "Chart";

/**
 * A chart plus the accessible surface around it.
 *
 * The chart's own SVG is not readable: recharts draws axes and series as
 * geometry, so a screen reader announces a bare graphic. This wrapper gives
 * every chart the same two things, so no panel can have one and skip the other:
 *
 *   * `aria-label` naming what is plotted, and
 *   * a `role="figure"` rather than `role="img"`. `img` tells assistive tech to
 *     treat the subtree as a single opaque image, which would hide the axis
 *     tick text and any legend inside it. `figure` labels the region and leaves
 *     its contents readable.
 *
 * `description` is rendered as a visually-hidden text alternative for the values
 * the geometry cannot convey, which is the one thing a chart plot cannot
 * recover on its own.
 */
function ChartFigure({
  ariaLabel,
  description,
  testId,
  className,
  config,
  children,
}: {
  ariaLabel: string;
  description?: string;
  testId: string;
  className?: string;
  config: ChartConfig;
  children: React.ReactNode;
}) {
  return (
    <figure
      role="figure"
      aria-label={ariaLabel}
      data-testid={testId}
      className={className}
    >
      <ChartContainer config={config}>{children}</ChartContainer>
      {description ? (
        <figcaption className="sr-only">{description}</figcaption>
      ) : null}
    </figure>
  );
}

/**
 * The `--color-<key>` custom properties the config names, scoped to this one
 * chart's `data-chart` id. Scoped rather than global on purpose: two charts on
 * one page with different palettes must not overwrite each other's series
 * colours, and `useId` keeps React's server/client ids in agreement.
 */
const ChartStyle = ({ id, config }: { id: string; config: ChartConfig }) => {
  const colorConfig = Object.entries(config).filter(
    ([, config]) => config.theme || config.color,
  );

  if (!colorConfig.length) {
    return null;
  }

  return (
    <style
      dangerouslySetInnerHTML={{
        __html: Object.entries(THEMES)
          .map(
            ([theme, prefix]) => `
${prefix} [data-chart=${id}] {
${colorConfig
  .map(([key, itemConfig]) => {
    const color =
      itemConfig.theme?.[theme as keyof typeof itemConfig.theme] ||
      itemConfig.color;
    return color ? `  --color-${key}: ${color};` : null;
  })
  .join("\n")}
}
`,
          )
          .join("\n"),
      }}
    />
  );
};

const ChartTooltip = RechartsPrimitive.Tooltip;

/**
 * The tooltip body. Its props are recharts' own TOOLTIP CONTENT props, not
 * `<Tooltip>`'s - recharts 3 reads `active`/`payload`/`label` off the chart
 * context and clones them into the content element. They are therefore typed
 * optional here: a caller writes `<ChartTooltipContent formatter={...} />` and
 * recharts fills the rest in, but TypeScript cannot know that a clone is
 * coming. Getting this wrong is invisible at runtime and loud at compile time,
 * which is the better of the two failures.
 *
 * `color` is gone from this surface on purpose: recharts 3's tooltip takes no
 * per-tooltip colour override, and a shim that quietly ignored one would be a
 * prop that looks like it works.
 */
const ChartTooltipContent = React.forwardRef<
  HTMLDivElement,
  Partial<TooltipContentProps> &
    React.ComponentProps<"div"> & {
      hideLabel?: boolean;
      hideIndicator?: boolean;
      indicator?: "line" | "dot" | "dashed";
      nameKey?: string;
      labelKey?: string;
    }
>(
  (
    {
      active,
      payload,
      className,
      indicator = "dot",
      hideLabel = false,
      hideIndicator = false,
      label,
      labelFormatter,
      labelClassName,
      formatter,
      nameKey,
      labelKey,
    },
    ref,
  ) => {
    const { config } = useChart();

    const tooltipLabel = React.useMemo(() => {
      if (hideLabel || !payload?.length) {
        return null;
      }

      const [item] = payload;
      const key = `${labelKey || item?.dataKey || item?.name || "value"}`;
      const itemConfig = getPayloadConfigFromPayload(config, item, key);
      const value =
        !labelKey && typeof label === "string"
          ? config[label as keyof typeof config]?.label || label
          : itemConfig?.label;

      if (labelFormatter) {
        return (
          <div className={cn("font-medium", labelClassName)}>
            {labelFormatter(value, payload)}
          </div>
        );
      }

      if (!value) {
        return null;
      }

      return <div className={cn("font-medium", labelClassName)}>{value}</div>;
    }, [
      label,
      labelFormatter,
      payload,
      hideLabel,
      labelClassName,
      config,
      labelKey,
    ]);

    if (!active || !payload?.length) {
      return null;
    }

    const nestLabel = payload.length === 1 && indicator !== "dot";

    return (
      <div
        ref={ref}
        className={cn(
          "grid min-w-[8rem] items-start gap-1.5 rounded-lg border border-border/50 bg-background px-2.5 py-1.5 text-xs shadow-xl",
          className,
        )}
      >
        {!nestLabel ? tooltipLabel : null}
        <div className="grid gap-1.5">
          {payload
            .filter((item) => item.type !== "none")
            .map((item, index) => {
              const key = `${nameKey || item.name || item.dataKey || "value"}`;
              const itemConfig = getPayloadConfigFromPayload(config, item, key);
              const indicatorColor = item.payload.fill || item.color;

              return (
                <div
                  key={`${nameKey || item.name || "series"}-${index}`}
                  className={cn(
                    "flex w-full flex-wrap items-stretch gap-2 [&>svg]:h-2.5 [&>svg]:w-2.5 [&>svg]:text-muted-foreground",
                    indicator === "dot" && "items-center",
                  )}
                >
                  {formatter && item?.value !== undefined && item.name ? (
                    formatter(item.value, item.name, item, index, item.payload)
                  ) : (
                    <>
                      {itemConfig?.icon ? (
                        <itemConfig.icon />
                      ) : (
                        !hideIndicator && (
                          <div
                            className={cn(
                              "shrink-0 rounded-[2px] border-[--color-border] bg-[--color-bg]",
                              {
                                "h-2.5 w-2.5": indicator === "dot",
                                "w-1": indicator === "line",
                                "w-0 border-[1.5px] border-dashed bg-transparent":
                                  indicator === "dashed",
                                "my-0.5": nestLabel && indicator === "dashed",
                              },
                            )}
                            style={
                              {
                                "--color-bg": indicatorColor,
                                "--color-border": indicatorColor,
                              } as React.CSSProperties
                            }
                          />
                        )
                      )}
                      <div
                        className={cn(
                          "flex flex-1 justify-between leading-none",
                          nestLabel ? "items-end" : "items-center",
                        )}
                      >
                        <div className="grid gap-1.5">
                          {nestLabel ? tooltipLabel : null}
                          <span className="text-muted-foreground">
                            {itemConfig?.label || item.name}
                          </span>
                        </div>
                        {item.value && (
                          <span className="font-mono font-medium tabular-nums text-foreground">
                            {item.value.toLocaleString()}
                          </span>
                        )}
                      </div>
                    </>
                  )}
                </div>
              );
            })}
        </div>
      </div>
    );
  },
);
ChartTooltipContent.displayName = "ChartTooltip";

const ChartLegend = RechartsPrimitive.Legend;

/**
 * The legend body, on the same terms as the tooltip body: `payload` and
 * `verticalAlign` arrive from the chart, not from `<Legend>`'s own props, so
 * they are picked off the default legend content's shape rather than off
 * `<Legend>`'s.
 */
const ChartLegendContent = React.forwardRef<
  HTMLDivElement,
  React.ComponentProps<"div"> &
    Pick<DefaultLegendContentProps, "payload" | "verticalAlign"> & {
      hideIcon?: boolean;
      nameKey?: string;
    }
>(
  (
    { className, hideIcon = false, payload, verticalAlign = "bottom", nameKey },
    ref,
  ) => {
    const { config } = useChart();

    if (!payload?.length) {
      return null;
    }

    return (
      <div
        ref={ref}
        className={cn(
          "flex items-center justify-center gap-4",
          verticalAlign === "top" ? "pb-3" : "pt-3",
          className,
        )}
      >
        {payload
          .filter((item) => item.type !== "none")
          .map((item) => {
            const key = `${nameKey || item.dataKey || "value"}`;
            const itemConfig = getPayloadConfigFromPayload(config, item, key);

            return (
              <div
                key={item.value}
                className={cn(
                  "flex items-center gap-1.5 [&>svg]:h-3 [&>svg]:w-3 [&>svg]:text-muted-foreground",
                )}
              >
                {itemConfig?.icon && !hideIcon ? (
                  <itemConfig.icon />
                ) : (
                  <div
                    className="h-2 w-2 shrink-0 rounded-[2px]"
                    style={{
                      backgroundColor: item.color,
                    }}
                  />
                )}
                {itemConfig?.label}
              </div>
            );
          })}
      </div>
    );
  },
);
ChartLegendContent.displayName = "ChartLegend";

/**
 * Resolve a hovered payload item to its config entry. Recharts reports a
 * datum under whatever key it was handed, so the series name can arrive either
 * as `item.name`, `item.dataKey`, or a field on the row itself - all three are
 * checked, in that order, before falling back to the raw key.
 */
function getPayloadConfigFromPayload(
  config: ChartConfig,
  payload: unknown,
  key: string,
) {
  if (typeof payload !== "object" || payload === null) {
    return undefined;
  }

  const payloadPayload =
    "payload" in payload &&
    typeof payload.payload === "object" &&
    payload.payload !== null
      ? payload.payload
      : undefined;

  let configLabelKey: string = key;

  if (
    key in payload &&
    typeof payload[key as keyof typeof payload] === "string"
  ) {
    configLabelKey = payload[key as keyof typeof payload] as string;
  } else if (
    payloadPayload &&
    key in payloadPayload &&
    typeof payloadPayload[key as keyof typeof payloadPayload] === "string"
  ) {
    configLabelKey = payloadPayload[
      key as keyof typeof payloadPayload
    ] as string;
  }

  return configLabelKey in config
    ? config[configLabelKey]
    : config[key as keyof typeof config];
}

export {
  ChartContainer,
  ChartFigure,
  ChartTooltip,
  ChartTooltipContent,
  ChartLegend,
  ChartLegendContent,
  ChartStyle,
};

// The recharts primitives a panel composes its series from, re-exported so the
// `recharts` specifier itself stays confined to this file (see the header's
// weight note).
//
// These are NAMED imports, not a destructure of the `RechartsPrimitive`
// namespace: `export const { Bar, ... } = RechartsPrimitive` is a runtime
// object operation, so a bundler cannot drop the members a given route never
// renders, and every panel route pays for the whole library. Named re-exports
// stay statically analysable, which is what keeps the chart routes inside the
// NFR-003 budget.
//
// Only the primitives the operator panels actually use are re-exported.
// Widening this list is how the boundary rots back into a pass-through of the
// whole library - and it is measured by `npm run check:pages`.
export {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Line,
  LineChart,
  XAxis,
  YAxis,
};
