import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Mukta } from "next/font/google";
import { AuthProvider } from "@/lib/auth/AuthContext";
import { LangProvider } from "@/lib/i18n/LangContext";
import "./globals.css";

// Single webfont, Latin + Devanagari (blueprint §1.3); self-hosted by
// next/font at build time. tokens.css appends the fallback stack.
//
// display: swap (PHASE-2.6 #205) was measured to drop CLS to ~0.22 on the
// throttled-4G homepage gate: on Linux CI runners the metric-matching fallback
// face (next/font's local('Arial') src) cannot resolve, so the late font swap
// shifts layout. display: optional makes the swap conditional on the font
// being ready before paint - no CLS on slow first visits, full Mukta once the
// files are cached (the homepage font budget ships ~160 KB).
const mukta = Mukta({
  subsets: ["devanagari", "latin"],
  weight: ["400", "500", "600", "700"],
  display: "optional",
  preload: false,
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
