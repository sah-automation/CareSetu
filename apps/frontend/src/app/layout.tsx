import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Mukta } from "next/font/google";
import { AuthProvider } from "@/lib/auth/AuthContext";
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

// AuthProvider mounts here rather than inside the dashboard group layout so
// every surface - public chrome included - reads session state through one
// shared context. (PHASE-2.6 T01, #192)
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={mukta.variable}>
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
