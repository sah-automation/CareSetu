// PHASE-2.6 T11 (#202): validation-matrix unit suite for the provider
// registration wizard's pure state module. Test names follow the ticket's
// acceptance criteria: per-step field schemas, upload discipline, and the
// type-preset normalization behind the CTA query-param flow.

import { describe, expect, it } from "vitest";

import type { WizardValues } from "./providerRegisterState";
import {
  MAX_UPLOAD_BYTES,
  UPLOAD_SLOTS,
  errorCount,
  formatFileSize,
  hasStepErrors,
  isOptionalSlot,
  isValidPassword,
  normalizeApplicationType,
  passwordStrengthScore,
  validateStep,
  validateUploadFile,
} from "./providerRegisterState";

const STRONG_PASSWORD = "correct-horse-battery1!";

function baseValues(overrides: Partial<WizardValues> = {}): WizardValues {
  return {
    fullName: "",
    email: "",
    password: "",
    mobile: "",
    degreeName: "",
    council: "",
    city: "",
    languages: "",
    businessName: "",
    address: "",
    serviceArea: "",
    ownerContact: "",
    uploads: {},
    declarationTruth: false,
    declarationConsent: false,
    declarationTerms: false,
    ...overrides,
  };
}

describe("type preset normalization (CTA ?type= flow)", () => {
  it("accepts the three CTA-carried types verbatim", () => {
    expect(normalizeApplicationType("doctor")).toBe("doctor");
    expect(normalizeApplicationType("lab")).toBe("lab");
    expect(normalizeApplicationType("chemist")).toBe("chemist");
  });

  it("defaults to doctor when the param is absent or junk", () => {
    expect(normalizeApplicationType(null)).toBe("doctor");
    expect(normalizeApplicationType("")).toBe("doctor");
    expect(normalizeApplicationType("Doctor")).toBe("doctor");
    expect(normalizeApplicationType("operator")).toBe("doctor");
  });
});

describe("step 1 - account basics validation matrix", () => {
  it("flags every required field on an empty step", () => {
    const errors = validateStep(1, "doctor", baseValues());
    expect(errors.fields.fullName).toBe("fullNameRequired");
    expect(errors.fields.email).toBe("emailInvalid");
    expect(errors.fields.password).toBe("passwordWeak");
    // Mobile for alerts is optional - absent stays clean.
    expect(errors.fields.mobile).toBeUndefined();
  });

  it("passes a complete account basics step", () => {
    const errors = validateStep(
      1,
      "doctor",
      baseValues({
        fullName: "Dr. Asha Kumar",
        email: "asha@example.com",
        password: STRONG_PASSWORD,
      }),
    );
    expect(hasStepErrors(errors)).toBe(false);
  });

  it("rejects malformed or wrong-length mobiles when present", () => {
    for (const bad of ["12345", "abcdefghij", "5999999999"]) {
      const errors = validateStep(1, "doctor", baseValues({ mobile: bad }));
      expect(errors.fields.mobile).toBe("mobileInvalid");
    }
  });

  it("accepts well-formed mobiles including +91 / 91 prefixes", () => {
    for (const good of ["9876543210", "+919876543210", "919876543210"]) {
      const errors = validateStep(1, "doctor", baseValues({ mobile: good }));
      expect(errors.fields.mobile).toBeUndefined();
    }
  });
});

describe("password schema (prototype strength hint)", () => {
  it("requires 12+ characters including a digit and a symbol", () => {
    expect(isValidPassword("short1!")).toBe(false);
    expect(isValidPassword("nodigitsorsymbols!!")).toBe(false);
    expect(isValidPassword("123456789012")).toBe(false);
    expect(isValidPassword(STRONG_PASSWORD)).toBe(true);
  });

  it("scores the meter by length plus digit/symbol bonuses, capped at 100", () => {
    expect(passwordStrengthScore("")).toBe(0);
    expect(passwordStrengthScore("abcd")).toBe(32);
    expect(passwordStrengthScore("abcd1234")).toBe(79);
    expect(passwordStrengthScore("abcdefghijkl")).toBe(96);
    // Raw formula overshoots; the meter clamps at 100.
    expect(passwordStrengthScore("abcdefghijkl1!")).toBe(100);
  });
});

describe("upload discipline checks (security standard client slice)", () => {
  it("accepts photo/PDF documents within the size ceiling", () => {
    expect(
      validateUploadFile({
        name: "degree.pdf",
        size: 1024,
        type: "application/pdf",
      }),
    ).toBeNull();
    expect(
      validateUploadFile({ name: "id.jpg", size: 500_000, type: "image/jpeg" }),
    ).toBeNull();
    // MIME-less files fall back to extension checking.
    expect(validateUploadFile({ name: "id.png", size: 10 })).toBeNull();
  });

  it("rejects disallowed types even with a permissive mime", () => {
    expect(validateUploadFile({ name: "script.exe", size: 10 })).toBe(
      "uploadWrongType",
    );
    expect(
      validateUploadFile({ name: "doc.txt", size: 10, type: "text/plain" }),
    ).toBe("uploadWrongType");
    expect(
      validateUploadFile({
        name: "forged.pdf",
        size: 10,
        type: "application/zip",
      }),
    ).toBe("uploadWrongType");
  });

  it("rejects files over the ceiling before anything else", () => {
    expect(
      validateUploadFile({
        name: "huge.pdf",
        size: MAX_UPLOAD_BYTES + 1,
        type: "application/pdf",
      }),
    ).toBe("uploadTooLarge");
    expect(
      validateUploadFile({ name: "exact.pdf", size: MAX_UPLOAD_BYTES }),
    ).toBeNull();
  });
});

describe("step 2 - professional / business identity matrix", () => {
  it("validates doctor fields only for doctor applications", () => {
    const errors = validateStep(2, "doctor", baseValues());
    expect(errors.fields.degreeName).toBe("degreeNameRequired");
    expect(errors.fields.council).toBe("councilRequired");
    expect(errors.fields.city).toBe("cityRequired");
    expect(errors.fields.languages).toBe("languagesRequired");
    expect(errors.fields.businessName).toBeUndefined();
  });

  it("validates partner fields for lab and chemist applications", () => {
    for (const applicationType of ["lab", "chemist"] as const) {
      const errors = validateStep(2, applicationType, baseValues());
      expect(errors.fields.businessName).toBe("businessNameRequired");
      expect(errors.fields.address).toBe("addressRequired");
      expect(errors.fields.serviceArea).toBe("serviceAreaRequired");
      expect(errors.fields.ownerContact).toBe("ownerContactInvalid");
      expect(errors.fields.degreeName).toBeUndefined();
    }
  });

  it("accepts owner contact in prefixed or bare form for partners", () => {
    for (const contact of ["9876543210", "+91 98765 43210"]) {
      const errors = validateStep(
        2,
        "lab",
        baseValues({
          businessName: "Seva Lab",
          address: "Main Road, Daltonganj",
          serviceArea: "Daltonganj + 15 km",
          ownerContact: contact,
        }),
      );
      expect(errors.fields.ownerContact).toBeUndefined();
    }
  });
});

describe("step 3 - credential slots per application type", () => {
  it("requires every non-optional slot of the current type", () => {
    for (const applicationType of ["doctor", "lab", "chemist"] as const) {
      const errors = validateStep(3, applicationType, baseValues());
      for (const slotId of UPLOAD_SLOTS[applicationType]) {
        if (isOptionalSlot(slotId)) continue;
        expect(errors.uploads[slotId]).toBe("uploadRequired");
      }
    }
  });

  it("never blocks on the optional accreditations slot", () => {
    const empty = validateStep(3, "lab", baseValues());
    expect(empty.uploads.accreditations).toBeUndefined();

    const attached = baseValues({
      uploads: {
        businessReg: { fileName: "gst.pdf", fileSizeBytes: 100 },
        kyc: { fileName: "kyc.png", fileSizeBytes: 200 },
      },
    });
    expect(hasStepErrors(validateStep(3, "lab", attached))).toBe(false);
  });

  it("re-checks stored files so discipline rules hold at review time", () => {
    const errors = validateStep(
      3,
      "chemist",
      baseValues({
        uploads: {
          drugLicense: { fileName: "license.exe", fileSizeBytes: 100 },
          shopLicense: { fileName: "shop.pdf", fileSizeBytes: 200 },
          kyc: { fileName: "kyc.png", fileSizeBytes: 300 },
        },
      }),
    );
    expect(errors.uploads.drugLicense).toBe("uploadWrongType");
    expect(errors.uploads.shopLicense).toBeUndefined();
    expect(errors.uploads.kyc).toBeUndefined();
  });
});

describe("step 4 - declarations gate submission", () => {
  it("requires all three declarations before submit", () => {
    const errors = validateStep(
      4,
      "doctor",
      baseValues({ declarationConsent: true }),
    );
    expect(errors.declarations.truth).toBe("declarationRequired");
    expect(errors.declarations.consent).toBeUndefined();
    expect(errors.declarations.terms).toBe("declarationRequired");
  });

  it("passes once all three are ticked", () => {
    const errors = validateStep(
      4,
      "doctor",
      baseValues({
        declarationTruth: true,
        declarationConsent: true,
        declarationTerms: true,
      }),
    );
    expect(hasStepErrors(errors)).toBe(false);
  });
});

describe("error accounting", () => {
  it("counts live errors only, ignoring keys cleared to undefined", () => {
    const errors = {
      fields: { fullName: undefined },
      uploads: { councilCert: "uploadRequired" as const },
      declarations: {},
    };
    expect(errorCount(errors)).toBe(1);
    expect(hasStepErrors(errors)).toBe(true);
  });
});

describe("formatFileSize", () => {
  it("formats bytes, kilobytes and megabytes for the slot display", () => {
    expect(formatFileSize(512)).toBe("512 B");
    expect(formatFileSize(2048)).toBe("2 KB");
    expect(formatFileSize(5 * 1024 * 1024)).toBe("5.0 MB");
  });
});
