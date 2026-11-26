// PHASE-2.6 T11 (#202): client-side validation, step gating and upload
// discipline for the four-step provider application wizard (/staff/register,
// blueprint §4.3, FEAT-014 open registration / gated activation).
//
// Field rules mirror the planned Phase 5 server schemas' observable minimums
// (prototype `provider-register.html` is the binding spec) - nothing
// stricter, so the server stays the authority once it exists. Upload checks
// are the client-side slice of security-phii-standards §5: type/size limits
// evaluated only on explicit user action. Nothing ever leaves the browser in
// this phase - submission names Phase 5 honestly (see phase5Notice).

import type { ProviderType } from "@/lib/directory/links";
import type { StaffAuthStrings } from "@/lib/i18n/dictionaries";

export type RegisterStrings = StaffAuthStrings["register"];

/** Client-side per-file size ceiling for credential uploads (10 MB).
 * Provisional client slice only - the prototype's photo/PDF copy is the
 * binding spec this phase; Phase 5's server schema owns the final limit and
 * reconciles it here (same convention as staffLoginState's email rule). */
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

const ALLOWED_EXTENSIONS = new Set(["jpg", "jpeg", "png", "webp", "pdf"]);
const ALLOWED_MIME_TYPES = new Set([
  "image/jpeg",
  "image/png",
  "image/webp",
  "application/pdf",
]);

export const ACCEPT_ATTRIBUTE =
  ".jpg,.jpeg,.png,.webp,.pdf,image/jpeg,image/png,image/webp,application/pdf";

// The three supply-side types arrive from the CTA query param (?type=...).
// Anything absent or unrecognised falls back to doctor - the primary supply
// side - rather than dead-ending the applicant.
export function normalizeApplicationType(raw: string | null): ProviderType {
  return raw === "lab" || raw === "chemist" ? raw : "doctor";
}

export type UploadSlotId =
  | "councilCert"
  | "degrees"
  | "photoId"
  | "businessReg"
  | "accreditations"
  | "kyc"
  | "drugLicense"
  | "shopLicense";

// Credential slots per application type (blueprint §4.3). Slot ids key both
// the dictionary labels (`register.slots.*`) and the wizard's file state.
export const UPLOAD_SLOTS: Record<ProviderType, readonly UploadSlotId[]> = {
  doctor: ["councilCert", "degrees", "photoId"],
  lab: ["businessReg", "accreditations", "kyc"],
  chemist: ["drugLicense", "shopLicense", "kyc"],
};

/** Accreditations stay optional; every other slot must carry a file. */
export function isOptionalSlot(slotId: UploadSlotId): boolean {
  return slotId === "accreditations";
}

// Council options carry stable ids so applications store locale-independent
// values; labels render from the dictionaries. Phase 5's partner schema owns
// the final enumeration - reconcile there, not ad hoc.
export const COUNCIL_OPTION_IDS = [
  "jharkhandSmc",
  "biharSmc",
  "other",
] as const;
export type CouncilOptionId = (typeof COUNCIL_OPTION_IDS)[number];

/** Resolves a stored council id back to its localized display label. */
export function councilLabel(id: string, labels: readonly string[]): string {
  const index = COUNCIL_OPTION_IDS.indexOf(id as CouncilOptionId);
  return index >= 0 ? labels[index] ?? id : id;
}

export interface UploadedFileState {
  fileName: string;
  fileSizeBytes: number;
}

export interface WizardValues {
  // Step 1 - account basics.
  fullName: string;
  email: string;
  password: string;
  /** Required contact channel for partner registration. */
  mobile: string;
  // Step 2 - professional identity (doctor).
  degreeName: string;
  council: string;
  city: string;
  languages: string;
  // Step 2 - business identity (lab / chemist).
  businessName: string;
  address: string;
  serviceArea: string;
  ownerContact: string;
  // Step 3 - credentials, keyed by slot id.
  uploads: Partial<Record<UploadSlotId, UploadedFileState>>;
  // Step 4 - declarations; submit requires all three.
  declarationTruth: boolean;
  declarationConsent: boolean;
  declarationTerms: boolean;
}

export function initialValues(): WizardValues {
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
  };
}

// Error keys double as dictionary keys under register.errors so components
// resolve copy with a single lookup - same convention as staffLoginState.

export type TextFieldKey =
  | "fullName"
  | "email"
  | "password"
  | "mobile"
  | "degreeName"
  | "council"
  | "city"
  | "languages"
  | "businessName"
  | "address"
  | "serviceArea"
  | "ownerContact";

export type TextFieldError =
  | "fullNameRequired"
  | "emailInvalid"
  | "passwordWeak"
  | "mobileInvalid"
  | "mobileRequired"
  | "degreeNameRequired"
  | "councilRequired"
  | "cityRequired"
  | "languagesRequired"
  | "businessNameRequired"
  | "addressRequired"
  | "serviceAreaRequired"
  | "ownerContactInvalid";

export type UploadError =
  | "uploadRequired"
  | "uploadWrongType"
  | "uploadTooLarge";

export type DeclarationKey = "truth" | "consent" | "terms";

export interface StepErrors {
  fields: Partial<Record<TextFieldKey, TextFieldError>>;
  uploads: Partial<Record<UploadSlotId, UploadError>>;
  declarations: Partial<Record<DeclarationKey, "declarationRequired">>;
}

// Accumulated component state may carry keys cleared to undefined; count
// only live errors.
function liveErrorCount(group: Record<string, unknown>): number {
  return Object.values(group).filter(Boolean).length;
}

export function hasStepErrors(errors: StepErrors): boolean {
  return errorCount(errors) > 0;
}

export function errorCount(errors: StepErrors): number {
  return (
    liveErrorCount(errors.fields) +
    liveErrorCount(errors.uploads) +
    liveErrorCount(errors.declarations)
  );
}

const EMAIL_PATTERN = /^\S+@\S+\.\S+$/;
const MOBILE_PATTERN = /^[6-9]\d{9}$/;

function isValidMobile(value: string): boolean {
  const digits = value.replace(/\D/g, "");
  if (digits.length === 12 && digits.startsWith("91")) {
    return MOBILE_PATTERN.test(digits.slice(2));
  }
  return MOBILE_PATTERN.test(digits);
}

/**
 * Password schema per the prototype's strength hint: at least 12 characters
 * including a number and a symbol. Mirrors the Phase 5 registration schema's
 * documented minimum.
 */
export function isValidPassword(password: string): boolean {
  return (
    password.length >= 12 &&
    /\d/.test(password) &&
    /[^a-zA-Z0-9]/.test(password)
  );
}

/**
 * Visual strength meter score (prototype formula): length-driven with
 * digit/symbol bonuses, capped at 100. Presentation only - the blocking rule
 * is isValidPassword above.
 */
export function passwordStrengthScore(password: string): number {
  return Math.min(
    100,
    password.length * 8 +
      (/\d/.test(password) ? 15 : 0) +
      (/[^a-zA-Z0-9]/.test(password) ? 20 : 0),
  );
}

/**
 * Client-side upload discipline (security standard §5 slice): allowed
 * document types and the size ceiling, checked against explicit user action
 * only. Returns the error key for the slot, or null when the file is fine.
 */
export function validateUploadFile(file: {
  name: string;
  size: number;
  type?: string;
}): UploadError | null {
  if (file.size > MAX_UPLOAD_BYTES) {
    return "uploadTooLarge";
  }
  const extension = file.name.includes(".")
    ? (file.name.split(".").pop() ?? "").toLowerCase()
    : "";
  const mimeOk = file.type ? ALLOWED_MIME_TYPES.has(file.type) : true;
  if (!mimeOk || !ALLOWED_EXTENSIONS.has(extension)) {
    return "uploadWrongType";
  }
  return null;
}

// Per-step validation. Each call validates exactly one step's slice, so the
// component can gate Continue per step while keeping messages per-field.

function validateStep1(values: WizardValues): StepErrors["fields"] {
  const errors: StepErrors["fields"] = {};
  if (values.fullName.trim().length === 0) {
    errors.fullName = "fullNameRequired";
  }
  if (!EMAIL_PATTERN.test(values.email.trim())) {
    errors.email = "emailInvalid";
  }
  if (!isValidPassword(values.password)) {
    errors.password = "passwordWeak";
  }
  if (values.mobile.trim().length === 0) {
    errors.mobile = "mobileRequired";
  } else if (!isValidMobile(values.mobile)) {
    errors.mobile = "mobileInvalid";
  }
  return errors;
}

function validateStep2(
  type: ProviderType,
  values: WizardValues,
): StepErrors["fields"] {
  const errors: StepErrors["fields"] = {};
  if (type === "doctor") {
    if (values.degreeName.trim().length === 0) {
      errors.degreeName = "degreeNameRequired";
    }
    if (values.council.trim().length === 0) {
      errors.council = "councilRequired";
    }
    if (values.city.trim().length === 0) {
      errors.city = "cityRequired";
    }
    if (values.languages.trim().length === 0) {
      errors.languages = "languagesRequired";
    }
  } else {
    if (values.businessName.trim().length === 0) {
      errors.businessName = "businessNameRequired";
    }
    if (values.address.trim().length === 0) {
      errors.address = "addressRequired";
    }
    if (values.serviceArea.trim().length === 0) {
      errors.serviceArea = "serviceAreaRequired";
    }
    if (!isValidMobile(values.ownerContact)) {
      errors.ownerContact = "ownerContactInvalid";
    }
  }
  return errors;
}

function validateStep3(
  type: ProviderType,
  values: WizardValues,
): StepErrors["uploads"] {
  const errors: StepErrors["uploads"] = {};
  for (const slotId of UPLOAD_SLOTS[type]) {
    const uploaded = values.uploads[slotId];
    if (!uploaded) {
      if (!isOptionalSlot(slotId)) {
        errors[slotId] = "uploadRequired";
      }
      continue;
    }
    const fileError = validateUploadFile({
      name: uploaded.fileName,
      size: uploaded.fileSizeBytes,
    });
    if (fileError) {
      errors[slotId] = fileError;
    }
  }
  return errors;
}

function validateStep4(values: WizardValues): StepErrors["declarations"] {
  const errors: StepErrors["declarations"] = {};
  if (!values.declarationTruth) {
    errors.truth = "declarationRequired";
  }
  if (!values.declarationConsent) {
    errors.consent = "declarationRequired";
  }
  if (!values.declarationTerms) {
    errors.terms = "declarationRequired";
  }
  return errors;
}

export function validateStep(
  step: number,
  type: ProviderType,
  values: WizardValues,
): StepErrors {
  switch (step) {
    case 1:
      return { fields: validateStep1(values), uploads: {}, declarations: {} };
    case 2:
      return {
        fields: validateStep2(type, values),
        uploads: {},
        declarations: {},
      };
    case 3:
      return {
        fields: {},
        uploads: validateStep3(type, values),
        declarations: {},
      };
    case 4:
      return { fields: {}, uploads: {}, declarations: validateStep4(values) };
    default:
      return { fields: {}, uploads: {}, declarations: {} };
  }
}

/** Focus order for moving to the first invalid control after a blocked step. */
export const FIELD_FOCUS_ORDER: Record<number, readonly string[]> = {
  1: ["fullName", "email", "password", "mobile"],
  2: [
    "degreeName",
    "council",
    "city",
    "languages",
    "businessName",
    "address",
    "serviceArea",
    "ownerContact",
  ],
  3: UPLOAD_SLOTS.doctor.concat(UPLOAD_SLOTS.lab, UPLOAD_SLOTS.chemist),
  4: ["truth", "consent", "terms"],
};

export function formatFileSize(bytes: number): string {
  if (bytes >= MAX_UPLOAD_BYTES || bytes >= 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  return `${Math.round(bytes / 1024)} KB`;
}
