// PHASE-8.1 T10 (#446): care API client contract. Every care mutation must
// emit the shared Idempotency-Key header (app/gateway/idempotency.py, api-
// standards §5) under mock transport, and reads must resolve the typed views
// (guards). Throws ApiError on network failure and malformed shapes.

import { afterEach, describe, expect, it, vi } from "vitest";

import { IDEMPOTENCY_KEY_HEADER, idempotencyKey } from "@/lib/idempotency";
import { ApiError } from "@/lib/api-errors";
import {
  approvePrescription,
  closeCaseWithoutRx,
  createRxDraft,
  fetchApprovedPrescription,
  fetchCareCase,
  fetchWorkingPrescription,
  listOpenCases,
  markConsultComplete,
  rejectPrescription,
  saveRxRevision,
  submitDoctorInput,
} from "./api";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const careCaseView = {
  case_id: 11,
  patient_id: 3,
  doctor_id: 7,
  pre_summary_id: 5,
  stage: "prescription_pending",
  forced_review: false,
  has_doctor_input: false,
  closed_at: null,
  close_reason: null,
  created_at: "2026-09-10T00:00:00Z",
  updated_at: "2026-09-10T00:00:00Z",
};

const prescriptionView = {
  prescription_id: 21,
  case_id: 11,
  status: "doctor_reviewed",
  source: "manual",
  attempt_no: 1,
  draft_snapshot: { rx_items: [] },
  issued_at: null,
  attributed_doctor: 7,
  attributed_doctor_name: null,
  items: [
    {
      rx_item_id: 31,
      prescription_id: 21,
      sequence: 1,
      name: "Paracetamol",
      dose: "500mg",
      duration: "3 days",
      frequency: "3 times daily",
    },
  ],
  created_at: "2026-09-10T00:00:00Z",
  updated_at: "2026-09-10T00:00:00Z",
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("care mutations emit the Idempotency-Key header", () => {
  const mutations: Array<[string, () => Promise<unknown>]> = [
    ["markConsultComplete", () => markConsultComplete(11)],
    [
      "submitDoctorInput",
      () => submitDoctorInput(11, { input_type: "voice", media_ref: "clip-1" }),
    ],
    ["createRxDraft", () => createRxDraft(11, { source: "ai_draft" })],
    [
      "saveRxRevision",
      () => saveRxRevision(11, 21, { rx_items: [{ name: "Paracetamol" }] }),
    ],
    ["approvePrescription", () => approvePrescription(11, 21)],
    [
      "rejectPrescription",
      () => rejectPrescription(11, 21, { reason: "needs a test first" }),
    ],
    [
      "closeCaseWithoutRx",
      () => closeCaseWithoutRx(11, { close_reason: "no_show" }),
    ],
  ];

  it.each(mutations)(
    "%s sends the Idempotency-Key header under mock transport",
    async (_name, run) => {
      const doctorInputResult = {
        input_id: 41,
        case_id: 11,
        input_type: "voice",
        media_ref: "clip-1",
        sensitive_class: "sensitive",
      };
      vi.stubGlobal(
        "fetch",
        vi.fn().mockImplementation((url: string) => {
          if (url.includes("/rx/"))
            return Promise.resolve(jsonResponse(prescriptionView));
          if (url.includes("/doctor-input"))
            return Promise.resolve(jsonResponse(doctorInputResult));
          return Promise.resolve(jsonResponse(careCaseView));
        }),
      );

      await run();

      const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
      const headers = new Headers(init.headers);
      expect(headers.get(IDEMPOTENCY_KEY_HEADER)).toBeTruthy();
    },
  );

  it("reuses a caller-supplied key so a retry is deduplicated", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(careCaseView)),
    );

    const key = idempotencyKey();
    await markConsultComplete(11, key);

    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get(IDEMPOTENCY_KEY_HEADER)).toBe(key);
  });

  it("emits a fresh distinct key for each new mutation", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementation(() => Promise.resolve(jsonResponse(careCaseView))),
    );

    await markConsultComplete(11);
    await markConsultComplete(12);

    const calls = vi.mocked(fetch).mock.calls as [string, RequestInit][];
    const first = new Headers(calls[0][1].headers).get(IDEMPOTENCY_KEY_HEADER);
    const second = new Headers(calls[1][1].headers).get(IDEMPOTENCY_KEY_HEADER);
    expect(first).toBeTruthy();
    expect(second).toBeTruthy();
    expect(first).not.toBe(second);
  });
});

describe("markConsultComplete", () => {
  it("POSTs to the consult-complete path and resolves the case view", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(careCaseView));
    vi.stubGlobal("fetch", fetchMock);

    await expect(markConsultComplete(11)).resolves.toEqual(careCaseView);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/v1/care/cases/11/consult-complete");
    expect(init.method).toBe("POST");
  });

  it("throws ApiError with NETWORK_ERROR on a network failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    await expect(markConsultComplete(11)).rejects.toMatchObject({
      code: "NETWORK_ERROR",
    });
  });

  it("throws ApiError with UNEXPECTED_ERROR on a malformed success shape", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ case_id: 11 })),
    );
    await expect(markConsultComplete(11)).rejects.toBeInstanceOf(ApiError);
  });
});

describe("listOpenCases", () => {
  it("resolves the doctor's open care cases", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([careCaseView]));
    vi.stubGlobal("fetch", fetchMock);

    await expect(listOpenCases()).resolves.toEqual([careCaseView]);
    expect((fetchMock.mock.calls[0] as [string])[0]).toBe(
      "http://localhost:8000/v1/care/cases",
    );
  });

  it("throws ApiError on a malformed list shape", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ items: [] })),
    );
    await expect(listOpenCases()).rejects.toBeInstanceOf(ApiError);
  });
});

describe("fetchCareCase", () => {
  it("resolves the case detail view", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(careCaseView));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchCareCase(11)).resolves.toEqual(careCaseView);
    expect((fetchMock.mock.calls[0] as [string])[0]).toBe(
      "http://localhost:8000/v1/care/cases/11",
    );
  });
});

describe("submitDoctorInput", () => {
  it("POSTs the input and resolves the doctor input result", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        input_id: 41,
        case_id: 11,
        input_type: "voice",
        media_ref: "clip-1",
        sensitive_class: "sensitive",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      submitDoctorInput(11, {
        input_type: "voice",
        media_ref: "clip-1",
        sensitive_class: "sensitive",
      }),
    ).resolves.toEqual({
      input_id: 41,
      case_id: 11,
      input_type: "voice",
      media_ref: "clip-1",
      sensitive_class: "sensitive",
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/v1/care/cases/11/doctor-input");
    expect(init.method).toBe("POST");
  });
});

describe("createRxDraft", () => {
  it("POSTs the draft request and resolves the prescription view", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(prescriptionView));
    vi.stubGlobal("fetch", fetchMock);

    await expect(createRxDraft(11, { source: "ai_draft" })).resolves.toEqual(
      prescriptionView,
    );

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/v1/care/cases/11/rx/draft");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ source: "ai_draft" });
  });
});

describe("saveRxRevision", () => {
  it("POSTs the working revision to the rx revision path", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(prescriptionView));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      saveRxRevision(11, 21, { rx_items: [{ name: "Paracetamol" }] }),
    ).resolves.toEqual(prescriptionView);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/v1/care/cases/11/rx/21/revision");
    expect(init.method).toBe("POST");
  });
});

describe("approvePrescription", () => {
  it("POSTs the verification declaration and resolves the issued view", async () => {
    const issuedView = {
      ...prescriptionView,
      status: "issued",
      issued_at: "2026-09-10T01:00:00Z",
      attributed_doctor_name: "Dr. Priya Verma",
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(issuedView));
    vi.stubGlobal("fetch", fetchMock);

    await expect(approvePrescription(11, 21)).resolves.toEqual(issuedView);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/v1/care/cases/11/rx/21/approve");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      verification_declaration: true,
    });
  });
});

describe("rejectPrescription", () => {
  it("POSTs the rejection reason", async () => {
    const rejectedView = {
      ...prescriptionView,
      status: "rejected",
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(rejectedView));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      rejectPrescription(11, 21, { reason: "needs a test first" }),
    ).resolves.toEqual(rejectedView);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/v1/care/cases/11/rx/21/reject");
    expect(JSON.parse(init.body as string)).toEqual({
      reason: "needs a test first",
    });
  });
});

describe("closeCaseWithoutRx", () => {
  it("POSTs the close reason and resolves the closed case", async () => {
    const closedView = { ...careCaseView, stage: "closed" };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(closedView));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      closeCaseWithoutRx(11, { close_reason: "no_show" }),
    ).resolves.toEqual(closedView);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/v1/care/cases/11/close");
    expect(init.method).toBe("POST");
  });
});

describe("fetchWorkingPrescription", () => {
  it("resolves the in-progress prescription view", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(prescriptionView));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchWorkingPrescription(11)).resolves.toEqual(
      prescriptionView,
    );
    expect((fetchMock.mock.calls[0] as [string])[0]).toBe(
      "http://localhost:8000/v1/care/cases/11/rx/current",
    );
  });

  it("throws ApiError when no working revision exists", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            code: "CARE_NOT_FOUND",
            message: "not found",
            trace_id: "t",
            details: {},
          },
          404,
        ),
      ),
    );
    await expect(fetchWorkingPrescription(11)).rejects.toMatchObject({
      code: "CARE_NOT_FOUND",
    });
  });
});

describe("fetchApprovedPrescription", () => {
  it("resolves the issued e-prescription view", async () => {
    const issuedView = {
      ...prescriptionView,
      status: "issued",
      issued_at: "2026-09-10T01:00:00Z",
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(issuedView));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchApprovedPrescription(21)).resolves.toEqual(issuedView);
    expect((fetchMock.mock.calls[0] as [string])[0]).toBe(
      "http://localhost:8000/v1/care/prescriptions/21",
    );
  });
});
