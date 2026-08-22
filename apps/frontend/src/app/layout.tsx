import type { Metadata } from "next";
import type { ReactNode } from "react";
import { AuthProvider } from "@/lib/auth/AuthContext";
import "./globals.css";

export const metadata: Metadata = {
  title: "CareSetu",
  description: "CareSetu care-loop platform",
};

// AuthProvider mounts here rather than inside the dashboard group layout so
// every surface - public chrome included - reads session state through one
// shared context. (PHASE-2.6 T01, #192)
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
