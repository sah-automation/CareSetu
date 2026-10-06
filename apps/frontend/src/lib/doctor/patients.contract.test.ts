// #624: the doctor console's frontend guards against the backend's real wire shape.
//
// The doctor Patients page died in the browser and shipped green. Its two page
// suites both mock `@/lib/doctor/api` wholesale, so the runtime guards inside
// that module never executed anywhere in CI; the drift between `photo_ref` and
// the backend's deliberate `has_photo` presence flag (security-phii-standards
// S2, ADR-0020 - the console must not learn where a patient's photo lives) was
// invisible until a doctor opened the page.
//
// This suite closes that gap at the only seam that runs the guards: the
// transport module itself, with the network layer stubbed. Asking
// `listDoctorPatients` / `fetchDoctorPatientDetail` what they do with a body is
// the behaviour a caller can observe - the guards are module-private, and a
// TypeScript type is erased at runtime, so neither is worth a test on its own.
//
// The fixture is not hand-copied. Every body below is built by walking the
// backend's published OpenAPI schema (openapi-doctor-console.json, regenerated
// by scripts/export_openapi_schemas.py and pinned by
// tests/unit/test_doctor_openapi_slice.py), so a backend rename fails here
// instead of failing a page. #652: the cases list joins the suite the same
// way - one generated removal case per row field, so a field added to
// DoctorCaseRow gets a guard without anyone remembering to add one.

import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  fetchDoctorPatientDetail,
  listDoctorCases,
  listDoctorPatients,
} from "./api";
import { request } from "@/lib/request";
import doctorConsoleSchema from "./openapi-doctor-console.json";

// The network layer is stubbed; the transport module under test is NOT.
vi.mock("@/lib/request", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/request")>();
  return { ...mod, request: vi.fn() };
});

const ask = vi.mocked(request);

interface OpenApiNode {
  $ref?: string;
  anyOf?: OpenApiNode[];
  enum?: string[];
  properties?: Record<string, OpenApiNode>;
  required?: string[];
  items?: OpenApiNode;
  type?: string;
}

const REF_PREFIX = "#/components/schemas/";
const schemas = (
  doctorConsoleSchema as unknown as { schemas: Record<string, OpenApiNode> }
).schemas;

function resolveRef(ref: string): OpenApiNode {
  const name = ref.slice(REF_PREFIX.length);
  const found = schemas[name];
  if (found === undefined) {
    throw new Error(
      `${name} is not in the exported OpenAPI slice; re-run the exporter`,
    );
  }
  return found;
}

/**
 * Build a body the backend would genuinely send, by walking the schema.
 *
 * Pydantic serialises every declared field, default included, so walking
 * `properties` yields the full wire shape rather than just the required subset.
 * `over` names the handful of values a case wants to assert on; everything else
 * takes the schema's first legal value.
 */
function body(
  name: string,
  over: Record<string, unknown> = {},
): Record<string, unknown> {
  return build(schemas[name], over) as Record<string, unknown>;
}

function build(node: OpenApiNode, over: Record<string, unknown> = {}): unknown {
  if (node.$ref !== undefined) return build(resolveRef(node.$ref), over);
  if (node.anyOf !== undefined) {
    // Prefer a concrete branch: `X | None` must not collapse the field to null.
    const solid = node.anyOf.filter((branch) => branch.type !== "null");
    return build(solid[0] ?? node.anyOf[0], over);
  }
  if (node.enum !== undefined) return node.enum[0];
  if (node.type === "object") {
    const shape: Record<string, unknown> = {};
    for (const [key, property] of Object.entries(node.properties ?? {})) {
      shape[key] = key in over ? over[key] : build(property);
    }
    return shape;
  }
  // No `over` for element nodes: an override names a field of THIS body, and
  // passing it down would let a parent field name collide with a nested one.
  if (node.type === "array") return [build(node.items ?? {})];
  if (node.type === "boolean") return true;
  if (node.type === "integer" || node.type === "number") return 1;
  if (node.type === "string") return "value";
  return null;
}

/** A patients-list body holding one row, or however many the case needs. */
function listBody(
  rows: Array<Record<string, unknown>> = [patientRow()],
): unknown {
  return body("PatientsListView", { items: rows, total: rows.length });
}

/** One list row exactly as the backend serialises it, with a photo present. */
function patientRow(
  over: Record<string, unknown> = {},
): Record<string, unknown> {
  return body("DoctorPatientRow", {
    patient_id: 7,
    name: "Asha Verma",
    bucket: "current",
    has_photo: true,
    ...over,
  });
}

/** A cases-list body holding one row, or however many the case needs. */
function casesBody(
  rows: Array<Record<string, unknown>> = [caseRow()],
): unknown {
  return body("DoctorCasesListView", { items: rows });
}

/** One case row exactly as the backend serialises it, clean and named. */
function caseRow(over: Record<string, unknown> = {}): Record<string, unknown> {
  return body("DoctorCaseRow", {
    case_id: 11,
    stage: "pre_summary",
    patient_name: "Asha Verma",
    patient_age: 45,
    forced_review: false,
    has_photo: true,
    ...over,
  });
}

/** One contact section exactly as the backend serialises it, with a photo present. */
function contactSection(
  over: Record<string, unknown> = {},
): Record<string, unknown> {
  return body("ContactSection", {
    name: "Asha Verma",
    has_photo: true,
    ...over,
  });
}

/** One patient detail exactly as the backend serialises it, fully granted. */
function patientDetail(
  over: Record<string, unknown> = {},
): Record<string, unknown> {
  return body("DoctorPatientDetailView", {
    patient_id: 7,
    bucket: "current",
    contact: contactSection(),
    ...over,
  });
}

/** Ask a real read path to refuse a body, and report whether it did. */
async function refuses(
  shape: unknown,
  read: () => Promise<unknown>,
  guardMessage: string,
): Promise<boolean> {
  ask.mockResolvedValue(shape);
  try {
    await read();
    return false;
  } catch (error) {
    expect(String(error)).toContain(guardMessage);
    return true;
  }
}

const listRefuses = (shape: unknown) =>
  refuses(shape, () => listDoctorPatients(), "unexpected patients list shape");

const casesRefuses = (shape: unknown) =>
  refuses(shape, () => listDoctorCases(), "unexpected cases list shape");

const detailRefuses = (shape: unknown) =>
  refuses(
    shape,
    () => fetchDoctorPatientDetail(7),
    "unexpected patient detail shape",
  );

beforeEach(() => {
  ask.mockReset();
});

describe("the doctor patients list against the served OpenAPI schema (#624)", () => {
  it("accepts a list the backend serves and hands the rows back", async () => {
    // The regression itself: this body was rejected by every row before the fix,
    // so the page rendered its error banner and no patients at all.
    ask.mockResolvedValue(listBody());

    const view = await listDoctorPatients();

    expect(view.total).toBe(1);
    expect(view.items[0].patient_id).toBe(7);
    expect(view.items[0].name).toBe("Asha Verma");
    expect(view.items[0].bucket).toBe("current");
    expect(view.items[0].has_photo).toBe(true);
  });

  it("accepts a photo-less row, which is a positive 'no photo', not an error", async () => {
    ask.mockResolvedValue(listBody([patientRow({ has_photo: false })]));

    const view = await listDoctorPatients();

    expect(view.items[0].has_photo).toBe(false);
  });

  it("never asks the client for the private photo storage key", async () => {
    // The backend's route test asserts the same absence from the other side
    // (tests/unit/test_doctor_patients_route.py). Asserting it here too keeps a
    // future "just send the ref" change from passing review unnoticed.
    ask.mockResolvedValue(listBody());

    const view = await listDoctorPatients();

    expect(view.items[0]).not.toHaveProperty("photo_ref");
  });

  // One case per declared field, generated rather than written out: a field added
  // to the backend DTO gets a removal case without anyone remembering to add one.
  it.each(Object.keys(schemas.DoctorPatientRow.properties ?? {}))(
    "refuses a row missing %s",
    async (key) => {
      const row = patientRow();
      delete row[key];

      expect(await listRefuses(listBody([row]))).toBe(true);
    },
  );

  it("refuses a row whose has_photo is a string rather than a boolean flag", async () => {
    // The realistic version of this drift: the flag arriving as the old ref, or
    // as a serialised string. The page branches on it, so a truthy "false"
    // string would fetch a photo that does not exist.
    expect(
      await listRefuses(
        listBody([patientRow({ has_photo: "objects/patients/7/me.jpg" })]),
      ),
    ).toBe(true);
    expect(
      await listRefuses(listBody([patientRow({ has_photo: "false" })])),
    ).toBe(true);
  });

  it("refuses a body that is not a patients list at all", async () => {
    expect(await listRefuses(null)).toBe(true);
    expect(await listRefuses("patients")).toBe(true);
    expect(await listRefuses({ total: 0 })).toBe(true);
    expect(await listRefuses({ items: {}, total: 0 })).toBe(true);
  });
});

describe("the doctor cases list against the served OpenAPI schema (#652)", () => {
  it("accepts a list the backend serves and hands the rows back", async () => {
    ask.mockResolvedValue(casesBody());

    const view = await listDoctorCases();

    expect(view.items).toHaveLength(1);
    expect(view.items[0].case_id).toBe(11);
    expect(view.items[0].stage).toBe("pre_summary");
    expect(view.items[0].patient_name).toBe("Asha Verma");
    expect(view.items[0].patient_age).toBe(45);
    expect(view.items[0].forced_review).toBe(false);
    expect(view.items[0].has_photo).toBe(true);
  });

  it("accepts a row whose patient the backend could not name or age", async () => {
    // The consent-gated projection may answer with nulls (story 13): the case
    // still belongs on the list, so the card's fallbacks - not a guard - own
    // what an unnamed patient reads as.
    ask.mockResolvedValue(
      casesBody([caseRow({ patient_name: null, patient_age: null })]),
    );

    const view = await listDoctorCases();

    expect(view.items[0].patient_name).toBeNull();
    expect(view.items[0].patient_age).toBeNull();
  });

  // One case per declared field, generated rather than written out: a field
  // added to the backend DTO gets a removal case without anyone remembering
  // to add one.
  it.each(Object.keys(schemas.DoctorCaseRow.properties ?? {}))(
    "refuses a row missing %s",
    async (key) => {
      const row = caseRow();
      delete row[key];

      expect(await casesRefuses(casesBody([row]))).toBe(true);
    },
  );

  it("refuses a row whose forced_review is a string rather than a boolean flag", async () => {
    // The realistic version of this drift: the flag arriving serialised. The
    // page branches on it to show the amber Verify chip, so a truthy "false"
    // would mark a clean case for verification before the doctor opened it.
    expect(
      await casesRefuses(casesBody([caseRow({ forced_review: "false" })])),
    ).toBe(true);
    expect(
      await casesRefuses(
        casesBody([caseRow({ forced_review: "objects/cases/11.json" })]),
      ),
    ).toBe(true);
  });

  it("refuses a row whose has_photo is a string rather than a boolean flag", async () => {
    expect(
      await casesRefuses(
        casesBody([caseRow({ has_photo: "objects/patients/7/me.jpg" })]),
      ),
    ).toBe(true);
    expect(
      await casesRefuses(casesBody([caseRow({ has_photo: "false" })])),
    ).toBe(true);
  });

  it("never asks the client for the private photo storage key", async () => {
    // The absence the patients route test asserts from the other side. The
    // fixture is built from the slice, so the moment the backend DECLARES a
    // `photo_ref` on this DTO the regenerated slice carries it into this body
    // and the assertion fails - forcing review of a field the guard would
    // happily pass and no card would ever render.
    ask.mockResolvedValue(casesBody());

    const view = await listDoctorCases();

    expect(view.items[0]).not.toHaveProperty("photo_ref");
  });

  it("refuses a body that is not a cases list at all", async () => {
    expect(await casesRefuses(null)).toBe(true);
    expect(await casesRefuses("cases")).toBe(true);
    expect(await casesRefuses({})).toBe(true);
    expect(await casesRefuses([])).toBe(true);
    expect(await casesRefuses({ items: {} })).toBe(true);
    expect(await casesRefuses({ items: [null] })).toBe(true);
  });
});

describe("the doctor patient detail against the served OpenAPI schema (#624)", () => {
  it("accepts a detail the backend serves and hands it back", async () => {
    ask.mockResolvedValue(patientDetail());

    const detail = await fetchDoctorPatientDetail(7);

    expect(detail.patient_id).toBe(7);
    expect(detail.contact?.name).toBe("Asha Verma");
    expect(detail.contact?.has_photo).toBe(true);
  });

  it("never asks the client for the private photo storage key", async () => {
    ask.mockResolvedValue(patientDetail());

    const detail = await fetchDoctorPatientDetail(7);

    expect(detail.contact).not.toHaveProperty("photo_ref");
  });

  it("accepts a detail whose sections the doctor is not granted", async () => {
    // ADR-0019: an ungranted section arrives as null, which the page renders as
    // the calm "not shared" state. It must not be mistaken for malformed data.
    ask.mockResolvedValue(
      patientDetail({
        granted_scopes: ["lab_results"],
        contact: null,
        consultation_history: null,
        health_background: null,
      }),
    );

    const detail = await fetchDoctorPatientDetail(7);

    expect(detail.contact).toBeNull();
    expect(detail.consultation_history).toBeNull();
    expect(detail.health_background).toBeNull();
  });

  it.each(Object.keys(schemas.DoctorPatientDetailView.properties ?? {}))(
    "refuses a detail missing %s",
    async (key) => {
      const detail = patientDetail();
      delete detail[key];

      expect(await detailRefuses(detail)).toBe(true);
    },
  );

  it.each(Object.keys(schemas.ContactSection.properties ?? {}))(
    "refuses a contact section missing %s",
    async (key) => {
      const contact = contactSection();
      delete contact[key];

      expect(await detailRefuses(patientDetail({ contact }))).toBe(true);
    },
  );

  it("refuses a contact section whose has_photo is not a boolean flag", async () => {
    expect(
      await detailRefuses(
        patientDetail({
          contact: contactSection({ has_photo: "objects/patients/7/me.jpg" }),
        }),
      ),
    ).toBe(true);
  });

  it("refuses a detail whose sections are malformed rather than locked", async () => {
    expect(await detailRefuses(patientDetail({ contact: "Asha Verma" }))).toBe(
      true,
    );
    expect(
      await detailRefuses(
        patientDetail({ consultation_history: { entries: {} } }),
      ),
    ).toBe(true);
    expect(
      await detailRefuses(patientDetail({ health_background: "full_record" })),
    ).toBe(true);
  });

  it("refuses a body that is not a patient detail at all", async () => {
    expect(await detailRefuses(null)).toBe(true);
    expect(await detailRefuses("a patient")).toBe(true);
    expect(await detailRefuses([])).toBe(true);
  });
});
