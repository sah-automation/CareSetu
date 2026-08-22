import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Mukta } from "next/font/google";
import { AuthProvider } from "@/lib/auth/AuthContext";
import { LangProvider } from "@/lib/i18n/LangContext";
import "./globals.css";

// Single webfont, Latin + Devanagari (blueprint §1.3); self-hosted by
// next/font at build time. tokens.css appends the fallback stack.
const mukta = Mukta({
  subsets: ["devanagari", "latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
  variable: "--font-mukta",
});

export const metadata: Metadata = {
  title: "CareSetu",
  description: "CareSetu care-loop platform",
};

// AuthProvider and LangProvider mount here rather than inside the dashboard
// group layout so every surface - public chrome included - shares one session
// source and one app-wide locale (PHASE-2.6 T01 #192, T03 #194). <html lang>
// starts static "en" for SSR-safe hydration; LangProvider syncs it to the
// active locale after mount.
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={mukta.variable}>
      <body>
        <LangProvider>
          <AuthProvider>{children}</AuthProvider>
        </LangProvider>
      </body>
    </html>
  );
}
