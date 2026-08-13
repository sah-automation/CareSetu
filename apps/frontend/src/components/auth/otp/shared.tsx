"use client";

// MOD-001 patient auth shared UI atoms (PHASE-2 T9, #60), folded from the
// Variant B prototype's `shared.tsx`. The atoms are the styling vocabulary of
// the auth wizard; prototype-only chrome (mock OTP hint, state strip, demo
// toggles) is gone - this is the real flow, not a demo.

import { useRef } from "react";

import { IconRefresh } from "@/components/auth/icons";
import type { I18n, Lang } from "./otpState";
import styles from "./otpShared.module.css";

export function BrandHeader({
  t,
  lang,
  onLang,
}: {
  t: I18n;
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

export function OtpInput({
  value,
  onChange,
  autoFocus,
  disabled,
}: {
  value: string;
  onChange: (digits: string) => void;
  autoFocus?: boolean;
  disabled?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const boxes = Array.from({ length: 6 }, (_, i) => value[i] ?? "");
  return (
    <div
      className={styles.otpWrap}
      onClick={() => inputRef.current?.focus()}
      role="group"
      aria-label="OTP"
    >
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
        aria-label="Verification code"
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

export function ErrorMessage({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p className={styles.error} role="alert">
      {message}
    </p>
  );
}

export function NoticeMessage({ message }: { message: string | null }) {
  if (!message) return null;
  return <p className={styles.notice}>{message}</p>;
}

export function PrimaryButton({
  onClick,
  disabled,
  children,
  pending,
}: {
  onClick?: () => void;
  disabled?: boolean;
  pending?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      className={styles.btnPrimary}
      disabled={disabled || pending}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

export function GhostButton({
  onClick,
  disabled,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      className={styles.btnGhost}
      disabled={disabled}
      onClick={onClick}
    >
      <IconRefresh size={14} />
      {children}
    </button>
  );
}
