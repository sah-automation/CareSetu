// MOD-003 (FEAT-002 record / FEAT-018 metrics), #549: the patient
// health-background client contract (backend #534 snapshot + #535
// height/weight series). Two surfaces, both owner-only and resolved from the
// session subject: GET/PUT /v1/me/health-background is the snapshot plus the
// one-time `acknowledge_phi` flag that gates the FIRST save, and
// GET/POST /v1/me/health-background/metrics is the append-only measurement
// series. The client never sends a patient id and never sends an entry id - the
// row id is server-minted - and the page must never fabricate a snapshot the
// API did not answer.

import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-errors";
import { IDEMPOTENCY_KEY_HEADER } from "@/lib/idempotency";
import {
  appendHealthMetric,
  fetchHealthBackground,
  fetchHealthMetrics,
  saveHealthBackground,
  type HealthBackground,
  type HealthBackgroundView,
  type HealthMetricEntry,
} from "./api";

const background: HealthBackground = {
  blood_group: "B+",
  conditions: ["Asthma"],
  allergies: ["Penicillin"],
  medications: ["Salbutamol inhaler"],
  immunizations: ["Tetanus 2024"],
  family_history: ["Father - diabetes"],
};

const stored: HealthBackgroundView = {
  set: true,
  acknowledged: true,
  background,
};

const entry: HealthMetricEntry = {
  entry_id: 12,
  height_cm: 170,
  weight_kg: 68.5,
  recorded_at: "2026-09-26T10:00:00Z",
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchHealthBackground", () => {
  it("GETs the owner snapshot and resolves the typed view", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(stored));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchHealthBackground()).resolves.toEqual(stored);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/v1/me/health-background");
    expect(init.method).toBeUndefined();
    expect(init.credentials).toBe("include");
  });

  it("resolves the never-set answer as a real view, not a failure", async () => {
    // `set: false` is how the API says "you have not saved one yet" - the zone
    // renders an empty state from it, so a client that threw here would turn a
    // zero-setup patient into an error page.
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          jsonResponse({ set: false, acknowledged: false, background: null }),
        ),
    );

    await expect(fetchHealthBackground()).resolves.toEqual({
      set: false,
      acknowledged: false,
      background: null,
    });
  });

  it("rejects a response that is not a health-background view", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ nope: 1 })),
    );

    await expect(fetchHealthBackground()).rejects.toBeInstanceOf(ApiError);
  });

  it("surfaces the backend envelope's code and trace id", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            code: "RECORD_ACCESS_DENIED",
            message: "not yours",
            trace_id: "trace-hb-1",
            details: {},
          },
          403,
        ),
      ),
    );

    await expect(fetchHealthBackground()).rejects.toMatchObject({
      code: "RECORD_ACCESS_DENIED",
      traceId: "trace-hb-1",
    });
  });
});

describe("saveHealthBackground", () => {
  it("PUTs the snapshot with the first-save acknowledgment and no client id", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(stored));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      saveHealthBackground(background, { acknowledgePhi: true }),
    ).resolves.toEqual(stored);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/v1/me/health-background");
    expect(init.method).toBe("PUT");
    const headers = new Headers(init.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.get(IDEMPOTENCY_KEY_HEADER)).toBeTruthy();
    expect(JSON.parse(init.body as string)).toEqual({
      acknowledge_phi: true,
      background,
    });
  });

  it("keeps acknowledge_phi present and false on a later edit", async () => {
    // The backend refuses a first save that omits the flag, so the field is
    // always sent; false is what makes an edit an edit rather than a re-grant.
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(stored));
    vi.stubGlobal("fetch", fetchMock);

    await saveHealthBackground(background, { acknowledgePhi: false });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string).acknowledge_phi).toBe(false);
  });

  it("replays the caller's key on a retry so a lost response cannot double-save", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(stored));
    vi.stubGlobal("fetch", fetchMock);

    await saveHealthBackground(background, {
      acknowledgePhi: false,
      retryKey: "retry-hb-1",
    });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get(IDEMPOTENCY_KEY_HEADER)).toBe(
      "retry-hb-1",
    );
  });

  it("lets the ack-required refusal reach the caller as a typed error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            code: "HEALTH_BACKGROUND_ACK_REQUIRED",
            message: "the first save must acknowledge",
            trace_id: "trace-hb-2",
            details: {},
          },
          422,
        ),
      ),
    );

    await expect(
      saveHealthBackground(background, { acknowledgePhi: false }),
    ).rejects.toMatchObject({ code: "HEALTH_BACKGROUND_ACK_REQUIRED" });
  });
});

describe("fetchHealthMetrics", () => {
  it("GETs the series with the page bounds as query params", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ items: [entry], total: 1 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchHealthMetrics({ page: 2, perPage: 10 })).resolves.toEqual(
      {
        items: [entry],
        total: 1,
      },
    );

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toBe(
      "http://localhost:8000/v1/me/health-background/metrics?page=2&per_page=10",
    );
  });

  it("leaves the page size to the server unless the caller asks for one", async () => {
    // The route owns its own bound. Re-declaring it here would be a second
    // place for the number to drift, and the client never varies it anyway.
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await fetchHealthMetrics();

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toBe(
      "http://localhost:8000/v1/me/health-background/metrics?page=1",
    );
  });

  it("resolves the empty series as an empty page, not a failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ items: [], total: 0 })),
    );

    await expect(fetchHealthMetrics()).resolves.toEqual({
      items: [],
      total: 0,
    });
  });

  it("rejects a list whose items are not metric entries", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ items: [{ id: 1 }], total: 1 })),
    );

    await expect(fetchHealthMetrics()).rejects.toBeInstanceOf(ApiError);
  });
});

describe("appendHealthMetric", () => {
  it("POSTs the measurement and resolves the server-minted entry", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(entry, 201));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      appendHealthMetric({
        heightCm: 170,
        weightKg: 68.5,
        recordedAt: "2026-09-26T10:00:00.000Z",
      }),
    ).resolves.toEqual(entry);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/v1/me/health-background/metrics");
    expect(init.method).toBe("POST");
    const headers = new Headers(init.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.get(IDEMPOTENCY_KEY_HEADER)).toBeTruthy();
    // The request model forbids extra fields: a client-supplied id would be a
    // 422, so the payload carries only the three authored values.
    expect(JSON.parse(init.body as string)).toEqual({
      height_cm: 170,
      weight_kg: 68.5,
      recorded_at: "2026-09-26T10:00:00.000Z",
    });
  });

  it("omits a measurement the patient did not record", async () => {
    // Either value alone is a legitimate entry (a weigh-in, a height check);
    // the backend only insists that not both are absent.
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(entry, 201));
    vi.stubGlobal("fetch", fetchMock);

    await appendHealthMetric({
      heightCm: null,
      weightKg: 68.5,
      recordedAt: "2026-09-26T10:00:00.000Z",
    });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({
      weight_kg: 68.5,
      recorded_at: "2026-09-26T10:00:00.000Z",
    });
  });

  it("replays the caller's key on a retry so a lost response cannot double-append", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(entry, 201));
    vi.stubGlobal("fetch", fetchMock);

    await appendHealthMetric(
      { heightCm: 170, weightKg: null, recordedAt: "2026-09-26T10:00:00.000Z" },
      "retry-metric-1",
    );

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get(IDEMPOTENCY_KEY_HEADER)).toBe(
      "retry-metric-1",
    );
  });
});
