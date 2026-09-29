"use client";

// MOD-001 patient auth shared UI atoms (PHASE-2 T9, #60), folded from the
// Variant B prototype's `shared.tsx`. The atoms are the styling vocabulary of
// the auth wizard; prototype-only chrome (mock OTP hint, state strip, demo
// toggles) is gone - this is the real flow, not a demo.
//
// #571 widened the module for the partner code step (#572). Three additions,
// none of which changes what a user sees:
//
//  - `CountdownRing` moved in from `PatientAuthWizard`, so both wizards render
//    one ring instead of the patient keeping a private copy.
//  - `testId` on every atom an existing staff-suite selector resolves to, so
//    #572 can swap markup without rewriting ~77 selector references. The hook
//    has to land on the element the selector resolves to today, which is why
//    `OtpInput`'s lands on the hidden input and not on the box wrapper.
//  - `PrimaryButton`'s `type` passthrough. Enter-to-verify rides on native
//    implicit form submission, and a hardcoded `type="button"` would break it
//    in a browser while every test stayed green.
//
// The hook is the deliverable #572 consumes, so here is the whole map, with the
// element each selector resolves to *today* - which is the element the hook has
// to land on, or the staff suite needs rewriting. All 30 selectors below are
// `toHaveTextContent` / `fireEvent.change` against `data-testid`; none queries
// by role, so moving one to a different node is invisible to the suite.
//
//   selector                   atom             lands on
//   staff-submit               PrimaryButton    the <button>
//   partner-otp                OtpInput         the hidden <input>, NOT the
//                                               .otpWrap role="group" div
//   partner-error              ErrorMessage     the <p role="alert">
//   partner-resend             GhostButton      the <button> (icon inside it)
//   partner-notice             NoticeMessage    the <p> (add role="status" for
//                                               the banner, see below)
//   partner-demo-banner        NoticeMessage    the <p>; was a
//                                               <div role="status">, so carry
//                                               the role across or the async
//                                               banner stops announcing
//   partner-edit-number        EditLinkButton   the <button> (was a raw
//                                               <button className="text-sm
//                                               underline">, so expect to
//                                               reconcile the class)
//   partner-countdown          CountdownRing    the .ringTime <span>, the node
//                                               that holds the seconds; the
//                                               ring's wrapper is aria-hidden
//
// Six selectors have no atom and stay hand-marked raw elements in #572:
// `partner-attempts`, `partner-cooldown`, `partner-lockout` and
// `partner-resend-cooldown` are the attempts banner, `partner-code-hint` and
// `partner-code-expires` are layout <p>s. None is named in #571's acceptance
// criteria, and each is asserted once or twice, so they need no atom - but
// they do need a `data-testid` written onto them by hand.

import { useRef } from "react";

import type { AuthStrings, Lang } from "@/lib/i18n/dictionaries";
import { IconRefresh } from "@/components/auth/icons";
import { formatCountdown, OTP_TTL_SECONDS } from "./otpState";
import styles from "./otpShared.module.css";

export function BrandHeader({
  t,
  lang,
  onLang,
}: {
  t: AuthStrings;
  lang: Lang;
  onLang: (l: Lang) => void;
}) {
  return (
    <header className={styles.brandHeader}>
      <p className={styles.brand}>
        <span className={styles.brandMark} aria-hidden="true" />
        {t.brand}
      </p>
      <LangToggle lang={lang} onLang={onLang} />
    </header>
  );
}

export function LangToggle({
  lang,
  onLang,
}: {
  lang: Lang;
  onLang: (l: Lang) => void;
}) {
  return (
    <div className={styles.langToggle} role="group" aria-label="Language">
      <button
        type="button"
        className={`${styles.langBtn} ${
          lang === "en" ? styles.langActive : ""
        }`}
        aria-pressed={lang === "en"}
        onClick={() => onLang("en")}
      >
        EN
      </button>
      <button
        type="button"
        className={`${styles.langBtn} ${
          lang === "hi" ? styles.langActive : ""
        }`}
        aria-pressed={lang === "hi"}
        onClick={() => onLang("hi")}
      >
        <span lang="hi">हिंदी</span>
      </button>
    </div>
  );
}

export function FieldLabel({ children }: { children: React.ReactNode }) {
  return <label className={styles.label}>{children}</label>;
}

export function PhoneInput({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (raw: string) => void;
  placeholder: string;
}) {
  return (
    <div className={styles.phoneWrap}>
      <span className={styles.phonePrefix}>+91</span>
      <input
        className={styles.phoneInput}
        type="tel"
        inputMode="numeric"
        autoComplete="tel"
        placeholder={placeholder}
        value={value.replace(/^\+91/, "")}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

export function CountdownRing({
  seconds,
  testId,
}: {
  seconds: number;
  testId?: string;
}) {
  const r = 26;
  const c = 2 * Math.PI * r;
  const frac = Math.max(0, Math.min(1, seconds / OTP_TTL_SECONDS));
  const low = seconds <= 60;
  return (
    <div className={styles.ring} aria-hidden="true">
      <svg width="72" height="72" viewBox="0 0 72 72">
        <circle
          cx="36"
          cy="36"
          r={r}
          fill="none"
          stroke="var(--hairline)"
          strokeWidth="5"
        />
        <circle
          cx="36"
          cy="36"
          r={r}
          fill="none"
          stroke={low ? "var(--danger)" : "var(--accent)"}
          strokeWidth="5"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - frac)}
          transform="rotate(-90 36 36)"
        />
      </svg>
      <span
        className={`${styles.ringTime} ${low ? styles.ringTimeLow : ""}`}
        data-testid={testId}
      >
        {formatCountdown(seconds)}
      </span>
    </div>
  );
}

export function OtpInput({
  value,
  onChange,
  autoFocus,
  disabled,
  testId,
  label,
  invalid,
  describedBy,
}: {
  value: string;
  onChange: (digits: string) => void;
  autoFocus?: boolean;
  disabled?: boolean;
  testId?: string;
  /**
   * The field's accessible name, supplied by the caller because the caller owns
   * the locale. #576: this used to be a hardcoded `aria-label` on the input set
   * to the English "Verification code", and an `aria-label` outranks the
   * wrapping `<label>` in the accessible-name computation - so when #572 built
   * the partner step (whose visible label is `t.codeLabel`) on this atom, a
   * partner reading the step in Hindi saw the Hindi label and heard English.
   * The name belongs to whichever wizard is asking, not to the atom.
   */
  label: string;
  /**
   * #576: `aria-invalid` and `aria-describedby` are the caller's to set, for
   * the same reason. The raw input #572 replaced carried both, pointed at
   * `partner-error`; the atom had nowhere to put them, so the swap dropped them
   * and no selector in the staff suite noticed.
   */
  invalid?: boolean;
  describedBy?: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const boxes = Array.from({ length: 6 }, (_, i) => value[i] ?? "");
  return (
    // #576: the wrapper used to be a `role="group"` div with an `aria-label`
    // set to the literal "OTP", a second hardcoded English name over the one
    // control it contains. Naming the input from the caller's string is enough,
    // and a group that repeats its only child's name is announced twice and
    // makes the field ambiguous to `getByLabelText`. The boxes are decorative;
    // the input is the control.
    <div className={styles.otpWrap} onClick={() => inputRef.current?.focus()}>
      <input
        ref={inputRef}
        className={styles.otpHiddenInput}
        type="tel"
        inputMode="numeric"
        autoComplete="one-time-code"
        autoFocus={autoFocus}
        value={value}
        maxLength={6}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        aria-label={label}
        aria-invalid={invalid ? true : undefined}
        aria-describedby={describedBy}
        data-testid={testId}
      />
      {boxes.map((digit, i) => (
        <span
          key={i}
          className={`${styles.otpBox} ${
            i === value.length ? styles.otpBoxActive : ""
          }`}
        >
          {digit}
        </span>
      ))}
    </div>
  );
}

export function ErrorMessage({
  message,
  testId,
  id,
}: {
  message: string | null;
  testId?: string;
  /**
   * #576: `aria-describedby` resolves against a DOM `id`, not a test id. The
   * partner phone and code inputs both point at `"partner-error"`, but the
   * element carrying that `data-testid` had no `id`, so both references dangled
   * and a screen reader read the field with no description at all. A caller that
   * wires `describedBy` passes the same string here.
   */
  id?: string;
}) {
  if (!message) return null;
  return (
    <p className={styles.error} role="alert" data-testid={testId} id={id}>
      {message}
    </p>
  );
}

/**
 * `role` is a prop rather than a fixed attribute because the atoms' callers
 * disagree, and the disagreement is invisible to the suite: the patient
 * wizard's notice is plain body copy, while the staff step's demo banner is a
 * `role="status"` region that appears asynchronously. Swapping the banner for a
 * role-less `NoticeMessage` would drop the announcement with all four of its
 * assertions still green, so the role is a thing the atom can carry rather than
 * something each caller has to remember. Defaulting either way would be a
 * silent change on the other surface.
 */
export function NoticeMessage({
  message,
  testId,
  role,
}: {
  message: string | null;
  testId?: string;
  role?: "status" | "alert";
}) {
  if (!message) return null;
  return (
    <p className={styles.notice} role={role} data-testid={testId}>
      {message}
    </p>
  );
}

export function PrimaryButton({
  onClick,
  disabled,
  children,
  pending,
  testId,
  type,
}: {
  onClick?: () => void;
  disabled?: boolean;
  pending?: boolean;
  children: React.ReactNode;
  testId?: string;
  /**
   * Defaults to `"button"` on purpose. Implicit form submission - Enter in a
   * form's field - is the spec's activation of the form's default button, so
   * a caller that needs Enter-to-verify inside a real form has to say
   * `type="submit"`; the default keeps every other call site a non-submitting
   * button.
   */
  type?: "button" | "submit" | "reset";
}) {
  return (
    <button
      type={type ?? "button"}
      className={styles.btnPrimary}
      disabled={disabled || pending}
      onClick={onClick}
      data-testid={testId}
    >
      {children}
    </button>
  );
}

export function GhostButton({
  onClick,
  disabled,
  children,
  testId,
}: {
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
  testId?: string;
}) {
  return (
    <button
      type="button"
      className={styles.btnGhost}
      disabled={disabled}
      onClick={onClick}
      data-testid={testId}
    >
      <IconRefresh size={14} />
      {children}
    </button>
  );
}

/**
 * The link-style "change number" control. Both wizards had their own raw
 * `<button>` for it; #571 folds them into one atom so the staff step gets a
 * hook to hang `partner-edit-number` on. No `type` prop: it is a navigation
 * control, and nothing it replaces was a form submit.
 */
export function EditLinkButton({
  onClick,
  children,
  testId,
  disabled,
}: {
  onClick: () => void;
  children: React.ReactNode;
  testId?: string;
  /**
   * Not decoration. The staff step's raw button is `disabled` while the
   * partner request is in flight, and the patient wizard's is not; dropping the
   * prop would let #572's swap re-enable the control mid-request with nothing
   * to catch it.
   */
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      className={styles.editLink}
      onClick={onClick}
      disabled={disabled}
      data-testid={testId}
    >
      {children}
    </button>
  );
}
