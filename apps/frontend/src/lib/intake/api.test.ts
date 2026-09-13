// PHASE-7 T15 (#359): intake HTTP client contract. Each function must send
// credentials, encode request bodies as JSON (or FormData for upload), and
// throw ApiError with the appropriate envelope code on failure.

import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-errors";
import {
  submitIntake,
  uploadIntakeMedia,
  reRecordIntake,
  fetchIntake,
  fetchPreSummary,
  savePatientEdits,
} from "./api";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("submitIntake", () => {
  it("POSTs a text intake and resolves the result", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ intake_id: 42, status: "captured" }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      submitIntake({ mode: "text", language: "en", text: "fever" }),
    ).resolves.toEqual({ intake_id: 42, status: "captured" });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/v1/intake/submit");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      mode: "text",
      language: "en",
      text: "fever",
      media_ref: undefined,
    });
  });

  it("POSTs a voice intake with media_ref", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ intake_id: 43, status: "captured" }));
    vi.stubGlobal("fetch", fetchMock);

    const mediaRef = {
      object_key: "intake/abc",
      media_type: "audio/webm",
      audio_duration_ms: 5000,
      file_size_bytes: 12000,
      record_attempt: 1,
    };
    await expect(
      submitIntake({ mode: "voice", language: "hi", media_ref: mediaRef }),
    ).resolves.toEqual({ intake_id: 43, status: "captured" });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toMatchObject({
      mode: "voice",
      language: "hi",
      media_ref: mediaRef,
    });
  });

  it("throws ApiError with NETWORK_ERROR on a network failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    await expect(
      submitIntake({ mode: "text", language: "en", text: "test" }),
    ).rejects.toMatchObject({ code: "NETWORK_ERROR" });
  });

  it("throws ApiError with the envelope code on a non-ok response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            code: "INTAKE_VALIDATION_ERROR",
            message: "invalid mode",
            trace_id: "t",
            details: {},
          },
          422,
        ),
      ),
    );
    await expect(
      submitIntake({ mode: "voice", language: "en" }),
    ).rejects.toMatchObject({ code: "INTAKE_VALIDATION_ERROR" });
  });

  it("throws ApiError with UNEXPECTED_ERROR on a malformed success shape", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ not_intake_id: true })),
    );
    await expect(
      submitIntake({ mode: "text", language: "en", text: "x" }),
    ).rejects.toBeInstanceOf(ApiError);
  });
});

describe("uploadIntakeMedia", () => {
  it("sends FormData with the file and resolves the clip ticket", async () => {
    const ticket = {
      object_key: "intake/def",
      media_type: "audio/webm",
      audio_duration_ms: 3000,
      file_size_bytes: 9000,
      record_attempt: 1,
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(ticket));
    vi.stubGlobal("fetch", fetchMock);

    const blob = new Blob(["audio"], { type: "audio/webm" });
    await expect(
      uploadIntakeMedia(blob, {
        filename: "clip.webm",
        audioDurationMs: 3000,
        fileSizeBytes: 9000,
      }),
    ).resolves.toEqual(ticket);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/v1/intake/upload-media?");
    expect(url).toContain("audio_duration_ms=3000");
    expect(url).toContain("file_size_bytes=9000");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    expect(init.credentials).toBe("include");
  });

  it("omits query params when not provided", async () => {
    const ticket = {
      object_key: "intake/ghi",
      media_type: "audio",
      audio_duration_ms: null,
      file_size_bytes: null,
      record_attempt: 1,
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(ticket));
    vi.stubGlobal("fetch", fetchMock);

    const blob = new Blob(["audio"]);
    await uploadIntakeMedia(blob);

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toBe("http://localhost:8000/v1/intake/upload-media");
  });

  it("throws ApiError with NETWORK_ERROR on a network failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    await expect(uploadIntakeMedia(new Blob())).rejects.toMatchObject({
      code: "NETWORK_ERROR",
    });
  });
});

describe("reRecordIntake", () => {
  it("POSTs the fresh clip ticket and resolves the re-record result", async () => {
    const result = {
      intake_id: 10,
      accepted: true,
      status: "structuring",
      record_attempts: 2,
      forced_text: false,
      media_ref_id: 5,
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(result));
    vi.stubGlobal("fetch", fetchMock);

    const mediaRef = {
      object_key: "intake/jkl",
      media_type: "audio/webm",
      audio_duration_ms: 4000,
      file_size_bytes: 10000,
      record_attempt: 2,
    };
    await expect(reRecordIntake(10, mediaRef)).resolves.toEqual(result);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/v1/intake/10/re-record");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ media_ref: mediaRef });
  });

  it("resolves a forced-text result when attempt cap is hit", async () => {
    const result = {
      intake_id: 10,
      accepted: false,
      status: "ready_for_review",
      record_attempts: 3,
      forced_text: true,
      media_ref_id: null,
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(result));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      reRecordIntake(10, {
        object_key: "x",
        media_type: "audio",
        audio_duration_ms: null,
        file_size_bytes: null,
        record_attempt: 3,
      }),
    ).resolves.toEqual(result);
  });
});

describe("fetchIntake", () => {
  it("GETs the intake detail and resolves", async () => {
    const detail = {
      intake_id: 7,
      patient_id: 2,
      mode: "voice",
      language: "hi",
      status: "structuring",
      record_attempts: 1,
      text: null,
      transcript: null,
      transcript_usability: null,
      forced_text: false,
      media_refs: [],
      created_at: "2026-09-08T10:00:00Z",
      updated_at: "2026-09-08T10:00:00Z",
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(detail));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchIntake(7)).resolves.toEqual(detail);
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toBe("http://localhost:8000/v1/intake/7");
  });

  it("throws ApiError with UNEXPECTED_ERROR on a bad shape", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ intake_id: 1 })),
    );
    await expect(fetchIntake(1)).rejects.toBeInstanceOf(ApiError);
  });
});

describe("fetchPreSummary", () => {
  it("GETs the pre-summary and resolves", async () => {
    const ps = {
      pre_summary_id: 3,
      intake_id: 7,
      structured_fields: { symptoms: ["fever"] },
      structuring_confidence: 0.82,
      low_confidence: false,
      review_state: "pending",
      patient_edits: null,
      doctor_corrections: null,
      review_attribution: null,
      reviewed_by: null,
      reviewed_at: null,
      created_at: "2026-09-08T10:01:00Z",
      updated_at: "2026-09-08T10:01:00Z",
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(ps));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchPreSummary(7)).resolves.toEqual(ps);
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toBe("http://localhost:8000/v1/intake/7/pre-summary");
  });
});

describe("savePatientEdits", () => {
  it("POSTs the field corrections and resolves the result", async () => {
    const result = {
      intake_id: 7,
      pre_summary_id: 3,
      patient_edits: { severity: "high" },
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(result));
    vi.stubGlobal("fetch", fetchMock);

    await expect(savePatientEdits(7, { severity: "high" })).resolves.toEqual(
      result,
    );

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/v1/intake/7/patient-edits");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      fields: { severity: "high" },
    });
  });

  it("throws ApiError with the envelope code on a 404", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            code: "INTAKE_NOT_FOUND",
            message: "intake not found",
            trace_id: "t",
            details: {},
          },
          404,
        ),
      ),
    );
    await expect(savePatientEdits(999, { x: 1 })).rejects.toMatchObject({
      code: "INTAKE_NOT_FOUND",
    });
  });
});
