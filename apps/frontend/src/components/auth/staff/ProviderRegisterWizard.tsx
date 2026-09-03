"use client";

// PHASE-2.6 T11 (#202): the four-step provider application wizard
// (/staff/register, blueprint §4.3) - account basics, professional/business
// identity, credentials upload, review & declarations. Applicants are
// unauthenticated: the route sits in the public carve-out of the staff route
// group and never touches session state.
//
// The application type arrives as the ?type= preset carried by the homepage
// providers band and staff-login CTAs (FEAT-014); absent or junk falls back
// to doctor. Validation lives in providerRegisterState.ts (pure, suite-
// tested). Uploads stay local this phase - type/size checks run only on
// explicit selection, nothing auto-uploads, and submitting names Phase 5
// honestly instead of pretending to persist.
//
// Layout: one small component per step (coding standards §8), all fed by the
// shared WizardActions seam; the root component owns state + gating only.

import { useCallback, useEffect, useRef, useState } from "react";

import type { ProviderType } from "@/lib/directory/links";
import { ApiError } from "@/lib/api-errors";
import { issueSession } from "@/lib/auth/api";
import { postLoginTarget } from "@/lib/auth/staff-routing";
import { saveSession } from "@/lib/auth/session";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import {
  registerPartner,
  submitCredentials,
  type CredentialType,
} from "@/lib/partner/api";

import {
  ACCEPT_ATTRIBUTE,
  COUNCIL_OPTION_IDS,
  FIELD_FOCUS_ORDER,
  UPLOAD_SLOTS,
  councilLabel,
  errorCount,
  formatFileSize,
  hasStepErrors,
  initialValues,
  isOptionalSlot,
  normalizeApplicationType,
  passwordStrengthScore,
  validateStep,
  validateUploadFile,
  type DeclarationKey,
  type RegisterStrings,
  type StepErrors,
  type TextFieldError,
  type TextFieldKey,
  type UploadSlotId,
  type WizardValues,
} from "./providerRegisterState";

export interface ProviderRegisterWizardProps {
  /** Raw ?type= query-param value from the CTA; null when absent/junk. */
  presetType?: string | null;
}

const STEP_LAST = 4;

// Stable DOM ids per logical field - kebab-cased for readability, consumed
// by labels, error paragraphs and the suites.
const FIELD_ID: Record<TextFieldKey, string> = {
  fullName: "pr-fullname",
  email: "pr-email",
  password: "pr-password",
  mobile: "pr-mobile",
  degreeName: "pr-degreename",
  council: "pr-council",
  city: "pr-city",
  languages: "pr-languages",
  businessName: "pr-businessname",
  address: "pr-address",
  serviceArea: "pr-servicearea",
  ownerContact: "pr-ownercontact",
};

const EMPTY_ERRORS: StepErrors = { fields: {}, uploads: {}, declarations: {} };

function slotToCredentialType(
  slotId: UploadSlotId,
  partnerType: ProviderType,
): CredentialType {
  switch (slotId) {
    case "councilCert":
      return "medical_registration";
    case "degrees":
      return "qualification_certificate";
    case "photoId":
      return "medical_registration";
    case "businessReg":
      return "lab_license";
    case "accreditations":
      return "accreditation";
    case "kyc":
      return partnerType === "lab" ? "lab_license" : "drug_license";
    case "drugLicense":
      return "drug_license";
    case "shopLicense":
      return "drug_license";
  }
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      const base64 = result.split(",")[1] ?? "";
      resolve(base64);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function normalizePhone(mobile: string): string {
  const countryCode = process.env.NEXT_PUBLIC_DEFAULT_COUNTRY_CODE ?? "91";
  const digits = mobile.replace(/\D/g, "");
  if (
    digits.length === countryCode.length + 10 &&
    digits.startsWith(countryCode)
  ) {
    return `+${digits}`;
  }
  return `+${countryCode}${digits}`;
}

interface WizardActions {
  setValue: <K extends keyof WizardValues>(
    key: K,
    value: WizardValues[K],
  ) => void;
  blurField: (field: TextFieldKey) => void;
  registerRef: (key: string) => (el: HTMLElement | null) => void;
  setUpload: (
    slotId: UploadSlotId,
    fileOrError: File | Exclude<ReturnType<typeof validateUploadFile>, null>,
  ) => void;
  removeUpload: (slotId: UploadSlotId) => void;
}

interface StepSectionProps {
  type: ProviderType;
  values: WizardValues;
  errors: StepErrors;
  actions: WizardActions;
  t: RegisterStrings;
}

function FieldError({ id, copy }: { id: string; copy?: string }) {
  if (!copy) return null;
  return (
    <p
      id={`${id}-error`}
      data-testid={`${id}-error`}
      className="mt-1 text-sm text-danger"
    >
      {copy}
    </p>
  );
}

interface TextFieldProps {
  field: TextFieldKey;
  label: string;
  value: string;
  error?: TextFieldError;
  onChange: (value: string) => void;
  onBlur: () => void;
  registerRef: (el: HTMLElement | null) => void;
  type?: string;
  placeholder?: string;
  autoComplete?: string;
  inputMode?: "numeric";
  maxLength?: number;
}

function TextField({
  field,
  label,
  value,
  error,
  onChange,
  onBlur,
  registerRef,
  type = "text",
  placeholder,
  autoComplete,
  inputMode,
  maxLength,
}: TextFieldProps) {
  const { lang } = useLang();
  const t = STRINGS[lang].staffAuth.register;
  const id = FIELD_ID[field];
  return (
    <div className="mb-4">
      <label htmlFor={id} className="mb-1 block text-sm font-medium">
        {label}
      </label>
      <input
        id={id}
        ref={registerRef}
        type={type}
        inputMode={inputMode}
        maxLength={maxLength}
        autoComplete={autoComplete}
        placeholder={placeholder}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onBlur={onBlur}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        className="w-full rounded-md border border-hairline bg-surface px-3 py-2"
        data-testid={id}
      />
      <FieldError id={id} copy={error ? t.errors[error] : undefined} />
    </div>
  );
}

/* Step 1 - account basics */

function StepAccountBasics({ values, errors, actions, t }: StepSectionProps) {
  return (
    <section data-testid="pr-step-1" aria-label={t.accountTitle}>
      <h1 className="mb-4 text-xl font-bold">{t.accountTitle}</h1>
      <TextField
        field="fullName"
        label={t.fields.fullName}
        value={values.fullName}
        error={errors.fields.fullName}
        onChange={(v) => actions.setValue("fullName", v)}
        onBlur={() => actions.blurField("fullName")}
        autoComplete="name"
        placeholder={t.fields.fullNamePlaceholder}
        registerRef={actions.registerRef("fullName")}
      />
      <TextField
        field="email"
        label={t.fields.email}
        value={values.email}
        error={errors.fields.email}
        onChange={(v) => actions.setValue("email", v)}
        onBlur={() => actions.blurField("email")}
        type="email"
        autoComplete="email"
        placeholder={t.fields.emailPlaceholder}
        registerRef={actions.registerRef("email")}
      />
      <div className="mb-4">
        <label
          htmlFor={FIELD_ID.password}
          className="mb-1 block text-sm font-medium"
        >
          {t.fields.password}
        </label>
        <input
          id={FIELD_ID.password}
          ref={actions.registerRef("password")}
          type="password"
          autoComplete="new-password"
          value={values.password}
          onChange={(event) => actions.setValue("password", event.target.value)}
          onBlur={() => actions.blurField("password")}
          aria-invalid={errors.fields.password ? true : undefined}
          aria-describedby={
            errors.fields.password ? `${FIELD_ID.password}-error` : "pr-pw-hint"
          }
          className="w-full rounded-md border border-hairline bg-surface px-3 py-2"
          data-testid={FIELD_ID.password}
        />
        <div
          className="mt-1 h-1 w-full overflow-hidden rounded bg-hairline-soft"
          aria-hidden="true"
        >
          <div
            data-testid="pw-strength"
            className="h-full bg-primary transition-all"
            style={{
              width: `${passwordStrengthScore(values.password)}%`,
            }}
          />
        </div>
        <p id="pr-pw-hint" className="mt-1 text-xs text-txt-muted">
          {t.fields.passwordHelp}
        </p>
        <FieldError
          id={FIELD_ID.password}
          copy={
            errors.fields.password
              ? t.errors[errors.fields.password]
              : undefined
          }
        />
      </div>
      <div className="mb-1">
        <label
          htmlFor={FIELD_ID.mobile}
          className="mb-1 block text-sm font-medium"
        >
          {t.fields.mobile}{" "}
          <span className="font-normal text-txt-muted">{t.optionalSuffix}</span>
        </label>
        <div className="flex items-center gap-2">
          <span className="text-sm text-txt-muted" aria-hidden="true">
            {t.mobilePrefix}
          </span>
          <input
            id={FIELD_ID.mobile}
            ref={actions.registerRef("mobile")}
            type="tel"
            inputMode="numeric"
            maxLength={10}
            autoComplete="tel-national"
            placeholder={t.fields.mobilePlaceholder}
            value={values.mobile}
            onChange={(event) => actions.setValue("mobile", event.target.value)}
            onBlur={() => actions.blurField("mobile")}
            aria-invalid={errors.fields.mobile ? true : undefined}
            aria-describedby={
              errors.fields.mobile ? `${FIELD_ID.mobile}-error` : undefined
            }
            className="min-w-0 flex-1 rounded-md border border-hairline bg-surface px-3 py-2"
            data-testid={FIELD_ID.mobile}
          />
        </div>
        <FieldError
          id={FIELD_ID.mobile}
          copy={
            errors.fields.mobile ? t.errors[errors.fields.mobile] : undefined
          }
        />
      </div>
    </section>
  );
}

/* Step 2 - professional / business identity */

function StepIdentity({ type, values, errors, actions, t }: StepSectionProps) {
  const title =
    type === "doctor" ? t.identityTitleDoctor : t.identityTitlePartner;

  function textField(
    field: TextFieldKey,
    label: string,
    extra?: Partial<TextFieldProps>,
  ) {
    return (
      <TextField
        field={field}
        label={label}
        value={values[field]}
        error={errors.fields[field]}
        onChange={(v) => actions.setValue(field, v)}
        onBlur={() => actions.blurField(field)}
        registerRef={actions.registerRef(field)}
        {...extra}
      />
    );
  }

  return (
    <section data-testid="pr-step-2" aria-label={title}>
      <h1 className="mb-4 text-xl font-bold">{title}</h1>
      {type === "doctor" ? (
        <>
          {textField("degreeName", t.fields.degreeName, {
            placeholder: t.fields.degreeNamePlaceholder,
          })}
          <div className="mb-4">
            <label
              htmlFor={FIELD_ID.council}
              className="mb-1 block text-sm font-medium"
            >
              {t.fields.council}
            </label>
            <select
              id={FIELD_ID.council}
              ref={actions.registerRef("council")}
              value={values.council}
              onChange={(event) =>
                actions.setValue("council", event.target.value)
              }
              onBlur={() => actions.blurField("council")}
              aria-invalid={errors.fields.council ? true : undefined}
              aria-describedby={
                errors.fields.council ? `${FIELD_ID.council}-error` : undefined
              }
              className="w-full rounded-md border border-hairline bg-surface px-3 py-2"
              data-testid={FIELD_ID.council}
            >
              <option value="">{t.fields.councilPlaceholder}</option>
              {COUNCIL_OPTION_IDS.map((id, index) => (
                <option key={id} value={id}>
                  {t.councils[index]}
                </option>
              ))}
            </select>
            <FieldError
              id={FIELD_ID.council}
              copy={
                errors.fields.council
                  ? t.errors[errors.fields.council]
                  : undefined
              }
            />
          </div>
          {textField("city", t.fields.city, {
            placeholder: t.fields.cityPlaceholder,
          })}
          {textField("languages", t.fields.languages, {
            placeholder: t.fields.languagesPlaceholder,
          })}
        </>
      ) : (
        <>
          {textField("businessName", t.fields.businessName)}
          <div className="mb-4">
            <label
              htmlFor={FIELD_ID.address}
              className="mb-1 block text-sm font-medium"
            >
              {t.fields.address}
            </label>
            <textarea
              id={FIELD_ID.address}
              ref={actions.registerRef("address")}
              rows={2}
              value={values.address}
              onChange={(event) =>
                actions.setValue("address", event.target.value)
              }
              onBlur={() => actions.blurField("address")}
              aria-invalid={errors.fields.address ? true : undefined}
              aria-describedby={
                errors.fields.address ? `${FIELD_ID.address}-error` : undefined
              }
              className="w-full rounded-md border border-hairline bg-surface px-3 py-2"
              data-testid={FIELD_ID.address}
            />
            <FieldError
              id={FIELD_ID.address}
              copy={
                errors.fields.address
                  ? t.errors[errors.fields.address]
                  : undefined
              }
            />
          </div>
          {textField("serviceArea", t.fields.serviceArea, {
            placeholder: t.fields.serviceAreaPlaceholder,
          })}
          {textField("ownerContact", t.fields.ownerContact, {
            type: "tel",
            inputMode: "numeric",
            maxLength: 10,
            placeholder: t.fields.mobilePlaceholder,
          })}
        </>
      )}
    </section>
  );
}

/* Step 3 - credentials upload */

function StepCredentials({
  type,
  values,
  errors,
  actions,
  t,
}: StepSectionProps) {
  const slots = UPLOAD_SLOTS[type];

  function handleUpload(slotId: UploadSlotId, fileList: FileList | null) {
    const file = fileList?.[0];
    if (!file) return;
    // Explicit user action only: check discipline rules and hold the file
    // client-side. Nothing is transmitted anywhere this phase.
    const uploadError = validateUploadFile(file);
    actions.setUpload(slotId, uploadError ?? file);
  }

  return (
    <section data-testid="pr-step-3" aria-label={t.credentialsTitle}>
      <h1 className="mb-1 text-xl font-bold">{t.credentialsTitle}</h1>
      <p className="mb-4 text-sm text-txt-muted">{t.credentialsNote}</p>
      <div className="space-y-3">
        {slots.map((slotId) => {
          const uploaded = values.uploads[slotId];
          const slotError = errors.uploads[slotId];
          const optional = isOptionalSlot(slotId);
          return (
            <div
              key={slotId}
              data-testid={`slot-${slotId}`}
              className="rounded-md border border-dashed border-hairline bg-page px-3 py-3"
            >
              <p className="text-sm font-semibold">
                {t.slots[slotId].label}
                {optional ? (
                  <span className="ml-1 font-normal text-txt-muted">
                    {t.optionalSuffix}
                  </span>
                ) : null}
              </p>
              {uploaded ? (
                <p
                  className="mt-1 flex items-center gap-2 text-sm"
                  data-testid={`slot-file-${slotId}`}
                >
                  <span className="min-w-0 truncate">
                    {uploaded.fileName} (
                    {formatFileSize(uploaded.fileSizeBytes)})
                  </span>
                  <button
                    type="button"
                    onClick={() => actions.removeUpload(slotId)}
                    data-testid={`slot-remove-${slotId}`}
                    className="ml-auto shrink-0 rounded-md border border-hairline px-2 py-0.5 text-xs"
                  >
                    {t.removeFile}
                  </button>
                </p>
              ) : (
                <>
                  <p className="text-xs text-txt-muted">
                    {optional ? t.slots[slotId].hint : t.uploadPrompt}
                  </p>
                  <input
                    type="file"
                    accept={ACCEPT_ATTRIBUTE}
                    onChange={(event) => {
                      handleUpload(slotId, event.target.files);
                      event.target.value = "";
                    }}
                    ref={actions.registerRef(slotId)}
                    aria-invalid={slotError ? true : undefined}
                    aria-describedby={
                      slotError ? `slot-${slotId}-error` : undefined
                    }
                    className="mt-2 block w-full text-sm"
                    data-testid={`slot-input-${slotId}`}
                  />
                  {slotError ? (
                    <p
                      id={`slot-${slotId}-error`}
                      data-testid={`slot-error-${slotId}`}
                      className="mt-1 text-sm text-danger"
                    >
                      {t.errors[slotError]}
                    </p>
                  ) : null}
                </>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

/* Step 4 - review & declarations */

function StepReview({
  type,
  values,
  errors,
  actions,
  t,
  toggleDeclaration,
}: StepSectionProps & {
  toggleDeclaration: (key: DeclarationKey, checked: boolean) => void;
}) {
  const slots = UPLOAD_SLOTS[type];

  const reviewRows: Array<{ label: string; value: string }> = [
    { label: t.review.applicant, value: values.fullName.trim() },
    { label: t.review.email, value: values.email.trim() },
    {
      label: t.review.mobile,
      value: values.mobile.trim()
        ? `${t.mobilePrefix} ${values.mobile.trim()}`
        : t.review.notProvided,
    },
    { label: t.review.type, value: t.typeLabels[type] },
  ];
  if (type === "doctor") {
    reviewRows.push(
      { label: t.fields.degreeName, value: values.degreeName },
      {
        label: t.fields.council,
        value: councilLabel(values.council, t.councils),
      },
      { label: t.fields.city, value: values.city },
      { label: t.fields.languages, value: values.languages },
    );
  } else {
    reviewRows.push(
      { label: t.fields.businessName, value: values.businessName },
      { label: t.fields.address, value: values.address },
      { label: t.fields.serviceArea, value: values.serviceArea },
      {
        label: t.fields.ownerContact,
        value: values.ownerContact
          ? `${t.mobilePrefix} ${values.ownerContact}`
          : "-",
      },
    );
  }

  const declarations: Array<{
    key: DeclarationKey;
    copy: string;
    propKey: "declarationTruth" | "declarationConsent" | "declarationTerms";
  }> = [
    { key: "truth", copy: t.declarations.truth, propKey: "declarationTruth" },
    {
      key: "consent",
      copy: t.declarations.consent,
      propKey: "declarationConsent",
    },
    { key: "terms", copy: t.declarations.terms, propKey: "declarationTerms" },
  ];

  return (
    <section data-testid="pr-step-4" aria-label={t.reviewTitle}>
      <h1 className="mb-4 text-xl font-bold">{t.reviewTitle}</h1>
      <dl className="mb-3 space-y-2 rounded-md border border-hairline bg-page px-3 py-3 text-sm">
        {reviewRows.map((row) => (
          <div key={row.label} className="flex justify-between gap-4">
            <dt className="shrink-0 text-txt-muted">{row.label}</dt>
            <dd className="text-right font-semibold">{row.value || "-"}</dd>
          </div>
        ))}
        <div className="flex justify-between gap-4">
          <dt className="text-txt-muted">{t.review.credentialsAttached}</dt>
          <dd className="font-semibold" data-testid="pr-review-creds-count">
            {t.review.fileCount(
              slots.filter((slotId) => values.uploads[slotId]).length,
            )}
          </dd>
        </div>
      </dl>
      <ul
        className="mb-4 space-y-1 text-xs text-txt-muted"
        data-testid="pr-review-files"
      >
        {slots.map((slotId) => (
          <li key={slotId} data-testid={`pr-review-slot-${slotId}`}>
            {t.slots[slotId].label}:{" "}
            {values.uploads[slotId]?.fileName ?? t.review.noFile}
          </li>
        ))}
      </ul>

      <fieldset className="space-y-3">
        <legend className="sr-only">{t.reviewTitle}</legend>
        {declarations.map(({ key, copy, propKey }) => {
          const declError = errors.declarations[key];
          return (
            <div key={key}>
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={values[propKey]}
                  onChange={(event) =>
                    toggleDeclaration(key, event.target.checked)
                  }
                  ref={actions.registerRef(key)}
                  aria-invalid={declError ? true : undefined}
                  aria-describedby={declError ? `decl-${key}-error` : undefined}
                  className="mt-0.5"
                  data-testid={`decl-${key}`}
                />
                <span>{copy}</span>
              </label>
              {declError ? (
                <p
                  id={`decl-${key}-error`}
                  data-testid={`decl-error-${key}`}
                  className="mt-1 pl-6 text-sm text-danger"
                >
                  {t.errors[declError]}
                </p>
              ) : null}
            </div>
          );
        })}
      </fieldset>
    </section>
  );
}

/* Root wizard - state, gating and honest submission only. */

export function ProviderRegisterWizard({
  presetType = null,
}: ProviderRegisterWizardProps) {
  const { lang } = useLang();
  const t = STRINGS[lang].staffAuth.register;

  const [type, setType] = useState<ProviderType>(
    normalizeApplicationType(presetType),
  );
  const [step, setStep] = useState(1);
  const [values, setValues] = useState<WizardValues>(initialValues);
  const [errors, setErrors] = useState<StepErrors>(EMPTY_ERRORS);
  const [attempted, setAttempted] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [serverError, setServerError] = useState<{
    message: string;
    traceId: string;
  } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [geoCoords, setGeoCoords] = useState<{
    lat: number;
    lng: number;
  } | null>(null);
  const fileRefs = useRef(new Map<UploadSlotId, File>());

  // Re-normalize when the CTA preset changes (e.g. hopping between the
  // Register-as-doctor/lab/chemist links). Identity + credential slices are
  // type-specific, so they reset; account basics carry over.
  useEffect(() => {
    setType(normalizeApplicationType(presetType));
    setValues((prev) => ({
      ...prev,
      degreeName: "",
      council: "",
      city: "",
      languages: "",
      businessName: "",
      address: "",
      serviceArea: "",
      ownerContact: "",
      uploads: {},
    }));
    setErrors(EMPTY_ERRORS);
    fileRefs.current.clear();
  }, [presetType]);

  // Collect real geolocation on mount; fall back to env-configured defaults
  // (Daltonganj coordinates for dev/CI) when the browser API is unavailable
  // or permission is denied.
  useEffect(() => {
    const fallbackLat = parseFloat(
      process.env.NEXT_PUBLIC_DEFAULT_LATITUDE ?? "24.04",
    );
    const fallbackLng = parseFloat(
      process.env.NEXT_PUBLIC_DEFAULT_LONGITUDE ?? "84.07",
    );

    if (!navigator.geolocation) {
      setGeoCoords({ lat: fallbackLat, lng: fallbackLng });
      return;
    }

    navigator.geolocation.getCurrentPosition(
      (position) => {
        setGeoCoords({
          lat: position.coords.latitude,
          lng: position.coords.longitude,
        });
      },
      () => {
        setGeoCoords({ lat: fallbackLat, lng: fallbackLng });
      },
      { timeout: 5000, maximumAge: 60000 },
    );
  }, []);

  const fieldRefs = useRef(new Map<string, HTMLElement>());
  function registerRef(key: string) {
    return (el: HTMLElement | null) => {
      if (el) {
        fieldRefs.current.set(key, el);
      } else {
        fieldRefs.current.delete(key);
      }
    };
  }

  function setValue<K extends keyof WizardValues>(
    key: K,
    value: WizardValues[K],
  ) {
    setValues((prev) => ({ ...prev, [key]: value }));
  }

  function setUpload(
    slotId: UploadSlotId,
    fileOrError: File | Exclude<ReturnType<typeof validateUploadFile>, null>,
  ) {
    if (typeof fileOrError === "string") {
      setValues((prev) => ({
        ...prev,
        uploads: { ...prev.uploads, [slotId]: undefined },
      }));
      setErrors((prev) => ({
        ...prev,
        uploads: { ...prev.uploads, [slotId]: fileOrError },
      }));
      fileRefs.current.delete(slotId);
      return;
    }
    setValues((prev) => ({
      ...prev,
      uploads: {
        ...prev.uploads,
        [slotId]: {
          fileName: fileOrError.name,
          fileSizeBytes: fileOrError.size,
        },
      },
    }));
    setErrors((prev) => {
      const uploads = { ...prev.uploads };
      delete uploads[slotId];
      return { ...prev, uploads };
    });
    fileRefs.current.set(slotId, fileOrError);
  }

  function removeUpload(slotId: UploadSlotId) {
    setValues((prev) => {
      const uploads = { ...prev.uploads };
      delete uploads[slotId];
      return { ...prev, uploads };
    });
    setErrors((prev) => {
      const uploads = { ...prev.uploads };
      delete uploads[slotId];
      return { ...prev, uploads };
    });
    fileRefs.current.delete(slotId);
  }

  function toggleDeclaration(key: DeclarationKey, checked: boolean) {
    setValue(
      key === "truth"
        ? "declarationTruth"
        : key === "consent"
          ? "declarationConsent"
          : "declarationTerms",
      checked,
    );
    if (checked) {
      setErrors((prev) => {
        const declarations = { ...prev.declarations };
        delete declarations[key];
        return { ...prev, declarations };
      });
    }
  }

  // §9.5 convention (mirrors the staff login form): validate the current
  // step on blur AND on advance; a blur re-checks just that field.
  function blurField(field: TextFieldKey) {
    const fresh = validateStep(step, type, values);
    setErrors((prev) => ({
      ...prev,
      fields: { ...prev.fields, [field]: fresh.fields[field] },
    }));
  }

  function focusFirstInvalid(fresh: StepErrors) {
    for (const key of FIELD_FOCUS_ORDER[step] ?? []) {
      const invalid =
        key in fresh.fields ||
        key in fresh.uploads ||
        key in fresh.declarations;
      if (!invalid) continue;
      fieldRefs.current.get(key)?.focus();
      return;
    }
  }

  function handlePrimary(event: React.FormEvent) {
    event.preventDefault();
    setNotice(null);
    setServerError(null);
    setAttempted(true);

    const fresh = validateStep(step, type, values);
    setErrors(fresh);

    if (hasStepErrors(fresh)) {
      focusFirstInvalid(fresh);
      return;
    }

    if (step < STEP_LAST) {
      setAttempted(false);
      setErrors(EMPTY_ERRORS);
      setStep(step + 1);
      return;
    }

    void handleSubmitPartner();
  }

  async function handleSubmitPartner() {
    if (submitting) return;

    const phone = values.mobile.trim();
    if (!phone) {
      setServerError({
        message: "Phone number is required",
        traceId: "",
      });
      return;
    }

    if (!geoCoords) {
      setServerError({
        message:
          "Unable to determine your location. Please allow location access and try again.",
        traceId: "",
      });
      return;
    }

    setSubmitting(true);
    try {
      const phoneE164 = normalizePhone(phone);

      await registerPartner({
        phone: phoneE164,
        partner_type: type,
        practice_name:
          type === "doctor" ? values.fullName : values.businessName || null,
        practice_address: type === "doctor" ? values.city : values.address,
        practice_latitude: geoCoords.lat,
        practice_longitude: geoCoords.lng,
        service_area_id: null,
      });

      const slots = UPLOAD_SLOTS[type];
      const credentialMap = new Map<CredentialType, string[]>();
      for (const slotId of slots) {
        const file = fileRefs.current.get(slotId);
        if (!file) continue;
        const credType = slotToCredentialType(slotId, type);
        const base64 = await fileToBase64(file);
        const existing = credentialMap.get(credType);
        if (existing) {
          existing.push(base64);
        } else {
          credentialMap.set(credType, [base64]);
        }
      }

      if (credentialMap.size > 0) {
        await submitCredentials({
          credentials: Array.from(credentialMap.entries()).map(
            ([credential_type, artifacts]) => ({
              credential_type,
              artifacts,
            }),
          ),
        });
      }

      const session = await issueSession(phoneE164);
      saveSession(session, phoneE164);

      window.location.href = postLoginTarget({
        surface: "staff",
        roles: ["partner"],
        partnerState: "pending",
      });
    } catch (err) {
      if (err instanceof ApiError) {
        setServerError({ message: err.message, traceId: err.traceId });
      } else {
        console.error("[provider-register] unexpected submit error", err);
        setServerError({
          message: "An unexpected error occurred. Please try again.",
          traceId: "",
        });
      }
    } finally {
      setSubmitting(false);
    }
  }

  function goBack() {
    setStep((current) => Math.max(1, current - 1));
    setAttempted(false);
    setErrors(EMPTY_ERRORS);
  }

  const actions: WizardActions = {
    setValue,
    blurField,
    registerRef,
    setUpload,
    removeUpload,
  };
  const sectionProps: StepSectionProps = { type, values, errors, actions, t };
  const total = errorCount(errors);

  return (
    <div>
      <span
        data-testid="pr-type-badge"
        className="inline-block rounded-full border border-hairline bg-surface px-3 py-1 text-sm font-semibold"
      >
        {t.typeBadge[type]}
      </span>

      <ol
        aria-label={t.stepperLabel}
        data-testid="pr-stepper"
        className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-sm"
      >
        {t.steps.map((label, index) => {
          const stepNumber = index + 1;
          const isCurrent = stepNumber === step;
          const isDone = stepNumber < step;
          return (
            <li
              key={label}
              aria-current={isCurrent ? "step" : undefined}
              className={
                isCurrent
                  ? "font-semibold"
                  : isDone
                    ? "text-txt-muted line-through"
                    : "text-txt-muted"
              }
            >
              {stepNumber}. {label}
            </li>
          );
        })}
      </ol>

      <form
        onSubmit={handlePrimary}
        noValidate
        data-testid="provider-register-form"
        className="mt-4 rounded-lg border border-hairline bg-surface p-6 shadow-card"
      >
        {notice ? (
          <div
            role="status"
            data-testid="pr-phase5-notice"
            className="mb-4 rounded-md border border-hairline bg-surface px-3 py-2 text-sm"
          >
            {notice}
          </div>
        ) : null}

        {serverError ? (
          <div
            role="alert"
            data-testid="pr-server-error"
            className="mb-4 rounded-md border border-danger bg-surface px-3 py-2 text-sm text-danger"
          >
            <p>{serverError.message}</p>
            {serverError.traceId ? (
              <p className="mt-1 text-xs text-txt-muted">
                Trace: {serverError.traceId}
              </p>
            ) : null}
          </div>
        ) : null}

        {attempted && total > 0 ? (
          <div
            role="alert"
            data-testid="pr-form-summary"
            className="mb-4 rounded-md border border-danger bg-surface px-3 py-2 text-sm text-danger"
          >
            {t.summaryTitle(total)}
          </div>
        ) : null}

        {step === 1 ? <StepAccountBasics {...sectionProps} /> : null}
        {step === 2 ? <StepIdentity {...sectionProps} /> : null}
        {step === 3 ? <StepCredentials {...sectionProps} /> : null}
        {step === 4 ? (
          <StepReview {...sectionProps} toggleDeclaration={toggleDeclaration} />
        ) : null}

        <hr className="my-5 border-hairline-soft" />

        <div className="flex items-center justify-between">
          <button
            type="button"
            onClick={goBack}
            disabled={step === 1}
            data-testid="pr-back"
            className="rounded-md border border-hairline px-4 py-2 text-sm disabled:opacity-40"
          >
            {t.back}
          </button>
          <button
            type="submit"
            data-testid={step === STEP_LAST ? "pr-submit" : "pr-next"}
            disabled={submitting}
            className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-on-accent disabled:opacity-50"
          >
            {submitting
              ? "Submitting..."
              : step === STEP_LAST
                ? t.submitApplication
                : t.continueCta}
          </button>
        </div>
      </form>
    </div>
  );
}
