"use client";

// PHASE-2.6 T03 (#194): app-wide language state. LangProvider mounts once at
// the root layout (alongside AuthProvider); every surface reads locale via
// useLang(). Blueprint §9.2 + spec #191 D1:
//   - default "en" until set; anonymous visitors adopt the device preference
//     - the previously stored "caresetu.lang", not navigator.languages -
//     when present (D1's "device localStorage preference");
//   - persistence is deliberately client-held this phase: for a signed-in
//     user the same stored value stands in as the profile-language field
//     intent until the profile backend exists (no server write here);
//   - <html lang> tracks the active locale (REQ-006 / blueprint story 5).
//
// One shared module store backs every mode: the provider mirrors it into
// context, and components mounted without a provider (the pre-existing suites
// render surfaces bare) subscribe to the same store directly - so toggling,
// persistence, and html-lang sync behave identically either way, and several
// provider-less consumers in one tree stay in sync with each other.

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import type { Lang } from "./dictionaries";

const LANG_KEY = "caresetu.lang";

export interface LangContextValue {
  lang: Lang;
  setLang: (lang: Lang) => void;
}

const LangContext = createContext<LangContextValue | null>(null);

function readStoredLang(): Lang | null {
  const raw = window.localStorage.getItem(LANG_KEY);
  return raw === "en" || raw === "hi" ? raw : null;
}

function saveStoredLang(lang: Lang): void {
  window.localStorage.setItem(LANG_KEY, lang);
}

let currentLang: Lang = "en";
const listeners = new Set<() => void>();

// Single mutation path: persist, flip the store, sync <html lang>.
function commitLang(next: Lang): void {
  if (next === currentLang) return;
  saveStoredLang(next);
  document.documentElement.lang = next;
  currentLang = next;
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

// The store starts at "en" and is only ever mutated from client code, so
// server rendering always snapshots "en" - matching the static <html lang="en">
// markup for hydration.
function getSnapshot(): Lang {
  return currentLang;
}

// Adopt the persisted choice after mount: the server and the first client
// render both see "en" so hydration matches; the flip happens once - the
// canonical Next.js SSR/client-mismatch guard, same as the wizard's gate.
// Idempotent, so any number of consumers may run it.
function adoptStoredLang(): void {
  const stored = readStoredLang();
  // The set-state-in-effect rule is intentionally suspended by callers - this
  // is that hydration guard.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  if (stored) commitLang(stored);
}

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(currentLang);

  // Mirror the shared store into React state so context consumers re-render.
  useEffect(() => subscribe(() => setLangState(getSnapshot())), []);

  useEffect(() => {
    adoptStoredLang();
  }, []);

  const value = useMemo(() => ({ lang, setLang: commitLang }), [lang]);

  return <LangContext.Provider value={value}>{children}</LangContext.Provider>;
}

export function useLang(): LangContextValue {
  const ctx = useContext(LangContext);
  // All hooks run unconditionally on every render; only the returned seam
  // branches on whether a provider is present above this consumer.
  const storeLang = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  useEffect(() => {
    if (!ctx) adoptStoredLang();
  }, [ctx]);

  return useMemo(
    () => ctx ?? { lang: storeLang, setLang: commitLang },
    [ctx, storeLang],
  );
}

// Test isolation only: the store is process-global, so suites reset it
// between tests alongside localStorage. Subscriptions stay untouched.
export function __resetLangForTests(): void {
  currentLang = "en";
}
