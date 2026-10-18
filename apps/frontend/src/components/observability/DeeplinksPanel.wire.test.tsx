// #736: the deep-links panel over the REAL read client and the REAL wire body.
//
// DeeplinksPanel.test.tsx feeds the panel a hand-written Deeplinks value, so it
// starts above the wire->model boundary: it can prove the panel renders what it is
// given and never could have caught a client that asked for the wrong thing or a
// guard that rejected the shape the route actually sends. This file holds that
// boundary - a real `fetchDeeplinks(context)`, a real `usePanelRead`, a stubbed
// transport and the exact JSON `/deeplinks` emits.
//
// The context the panel hands over is a trace id straight off a platform read - the
// error feed's `trace_id` - which is the whole point of #736: an operator clicking
// through from a row reaches that row's trace in Grafana, Sentry and Langfuse, under
// one identifier.

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchDeeplinks } from "@/lib/operator/observability";
import { usePanelRead } from "@/lib/operator/usePanelRead";

import { DeeplinksPanel } from "./DeeplinksPanel";

/** The identifier the error feed hands the operator, unchanged. */
const TRACE = "c7f2a1b0d3e4f5061728394a5b6c7d8e";

/**
 * The route's answer for a fully configured deployment asked about one trace.
 * `exclude_none` drops absent keys, so Langfuse's per-actor and per-session views
 * have no keys at all rather than nulls, and every filter the panel supplied is
 * visible in the URLs - which is the whole point of #736.
 */
const DEEPLINKS_WIRE = {
  trace_id: TRACE,
  grafana: {
    dashboard_uid: "caresetu-observability",
    dashboard_url:
      "https://acme.grafana.net/d/caresetu-observability/caresetu-observability?from=now-6h&to=now&var-service=caresetu-api&var-env=production",
    explore_url:
      "https://acme.grafana.net/explore?left=" +
      encodeURIComponent(
        `{"traceId":"${TRACE}","range":{"from":"now-6h","to":"now"}}`,
      ),
  },
  sentry: {
    project_id: "7654321",
    issues_url:
      "https://o4242.sentry.io/issues/?project=7654321&query=service%3A%22caresetu-api%22",
    trace_url:
      "https://o4242.sentry.io/issues/?project=7654321" +
      `&query=${encodeURIComponent(`trace_id:"${TRACE}"`)}`,
  },
  langfuse: {
    traces_url:
      "https://cloud.langfuse.com/project/pk-lf-1/traces?model=gpt-4o&name=ai_structure",
    trace_url: `https://cloud.langfuse.com/project/pk-lf-1/trace/${TRACE}`,
  },
};

function stubRouteWire(body: unknown) {
  const fetchMock = vi.fn((_input: RequestInfo | URL) =>
    Promise.resolve(
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** The panel exactly as a page mounts it: the real hook over the real client. */
function Panel({
  context = {},
}: {
  context?: Parameters<typeof fetchDeeplinks>[0];
}) {
  const read = usePanelRead(() => fetchDeeplinks(context));
  return <DeeplinksPanel read={read} />;
}

function hrefOf(testId: string): string | null {
  return screen.getByTestId(testId).getAttribute("href");
}

beforeEach(() => {
  window.localStorage.setItem("caresetu.access_jwt", "operator.jwt.value");
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("DeeplinksPanel over the real wire", () => {
  it("asks for the trace it was given and links it into all three tools", async () => {
    const fetchMock = stubRouteWire(DEEPLINKS_WIRE);

    render(<Panel context={{ trace_id: TRACE }} />);

    await waitFor(() => {
      expect(
        screen.getByTestId("observability-deeplink-grafana.dashboard_url"),
      ).toBeTruthy();
    });

    // The trace went out as the platform's own id, unmodified.
    expect(String(fetchMock.mock.calls[0]![0])).toContain(`trace_id=${TRACE}`);

    for (const key of [
      "grafana.explore_url",
      "sentry.trace_url",
      "langfuse.trace_url",
    ]) {
      expect(hrefOf(`observability-deeplink-${key}`)).toContain(TRACE);
    }
    expect(hrefOf("observability-deeplink-sentry.issues_url")).toContain(
      "service%3A%22caresetu-api%22",
    );
    expect(hrefOf("observability-deeplink-grafana.dashboard_url")).toContain(
      "var-env=production",
    );
    expect(hrefOf("observability-deeplink-langfuse.traces_url")).toContain(
      "name=ai_structure",
    );
  });

  it("renders an unconfigured vendor as nothing at all", async () => {
    // The wire carries no `langfuse` key - a deployment without Langfuse configured.
    const { langfuse: _absent, ...twoVendors } = DEEPLINKS_WIRE;
    stubRouteWire(twoVendors);

    render(<Panel context={{ trace_id: TRACE }} />);

    await waitFor(() => {
      expect(
        screen.getByTestId("observability-deeplink-sentry.issues_url"),
      ).toBeTruthy();
    });
    expect(
      screen.queryByTestId("observability-deeplink-langfuse.traces_url"),
    ).toBeNull();
    expect(screen.queryByText("Langfuse")).toBeNull();
    expect(screen.queryByTestId("empty-state-title")).toBeNull();
  });

  it("says the deployment has no vendor links when nothing is configured", async () => {
    // What the route sends with every vendor off: `{}`, not three nulls.
    stubRouteWire({});

    render(<Panel />);

    await waitFor(() => {
      expect(screen.getByTestId("empty-state-title").textContent).toBe(
        "No vendor links configured",
      );
    });
    expect(screen.queryByTestId("observability-deeplinks-list")).toBeNull();
  });
});
