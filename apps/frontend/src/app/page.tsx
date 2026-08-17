/**
 * Marketing Homepage - FEAT-002, FEAT-020, FEAT-007
 *
 * Public landing page for CareSetu. Server-rendered for SEO and fast load.
 * Replaces the previous root redirect to /patient.
 *
 * @see docs/agents/briefs/PHASE-2-5-T4-marketing-homepage.md
 */
import Link from "next/link";

const ctaButtonStyle = {
  display: "inline-block" as const,
  padding: "0.75rem 2rem",
  backgroundColor: "#2563eb",
  color: "#ffffff",
  borderRadius: "0.5rem",
  textDecoration: "none",
  fontWeight: "600" as const,
  fontSize: "1.125rem",
};

const featureCardStyle = {
  padding: "2rem",
  border: "1px solid #e2e8f0",
  borderRadius: "0.75rem",
  backgroundColor: "#f8fafc",
};

const iconBaseStyle = {
  width: "3rem",
  height: "3rem",
  borderRadius: "0.5rem",
  display: "flex" as const,
  alignItems: "center" as const,
  justifyContent: "center" as const,
  marginBottom: "1rem",
  fontSize: "1.5rem",
};

export default function MarketingHomepage() {
  return (
    <div
      style={{
        minHeight: "100vh",
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
        backgroundColor: "#f8fafc",
        color: "#1e293b",
      }}
    >
      {/* Header */}
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "1rem 2rem",
          backgroundColor: "#ffffff",
          borderBottom: "1px solid #e2e8f0",
        }}
      >
        <div
          style={{ fontSize: "1.5rem", fontWeight: "bold", color: "#2563eb" }}
        >
          CareSetu
        </div>
        <nav style={{ display: "flex", gap: "1rem", alignItems: "center" }}>
          <Link
            href="/login"
            style={{
              padding: "0.5rem 1rem",
              backgroundColor: "#2563eb",
              color: "#ffffff",
              borderRadius: "0.375rem",
              textDecoration: "none",
              fontWeight: "500",
            }}
          >
            Get Started
          </Link>
        </nav>
      </header>

      {/* Hero Section */}
      <main>
        <section
          style={{
            padding: "4rem 2rem",
            textAlign: "center",
            maxWidth: "800px",
            margin: "0 auto",
          }}
        >
          <h1
            style={{
              fontSize: "3rem",
              fontWeight: "bold",
              marginBottom: "1rem",
              color: "#0f172a",
            }}
          >
            Your Health Records, Your Control
          </h1>
          <p
            style={{
              fontSize: "1.25rem",
              color: "#64748b",
              marginBottom: "2rem",
              lineHeight: "1.6",
            }}
          >
            CareSetu is a voice-based clinical records platform that puts you in
            charge of your health data. Share records securely with doctors,
            labs, and pharmacies - only with your consent.
          </p>
          <Link href="/login" style={ctaButtonStyle}>
            Get Started
          </Link>
        </section>

        {/* Features Section */}
        <section
          style={{
            padding: "4rem 2rem",
            backgroundColor: "#ffffff",
          }}
        >
          <div
            style={{
              maxWidth: "1200px",
              margin: "0 auto",
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))",
              gap: "2rem",
            }}
          >
            {/* Feature 1: Longitudinal Records (FEAT-002) */}
            <div style={featureCardStyle}>
              <div style={{ ...iconBaseStyle, backgroundColor: "#dbeafe" }}>
                📋
              </div>
              <h3
                style={{
                  fontSize: "1.25rem",
                  fontWeight: "600",
                  marginBottom: "0.5rem",
                  color: "#0f172a",
                }}
              >
                Longitudinal Records
              </h3>
              <p style={{ color: "#64748b", lineHeight: "1.6" }}>
                Your complete health history in one place. From visits to
                prescriptions, everything is organized and accessible when you
                need it.
              </p>
            </div>

            {/* Feature 2: Consent-Gated Sharing (FEAT-002/020) */}
            <div style={featureCardStyle}>
              <div style={{ ...iconBaseStyle, backgroundColor: "#dcfce7" }}>
                🔒
              </div>
              <h3
                style={{
                  fontSize: "1.25rem",
                  fontWeight: "600",
                  marginBottom: "0.5rem",
                  color: "#0f172a",
                }}
              >
                Consent-Gated Sharing
              </h3>
              <p style={{ color: "#64748b", lineHeight: "1.6" }}>
                You decide who sees your records. Every share requires your
                explicit consent. Revoke access anytime with a single tap.
              </p>
            </div>

            {/* Feature 3: AI Pre-Summary (FEAT-007) */}
            <div style={featureCardStyle}>
              <div style={{ ...iconBaseStyle, backgroundColor: "#fef3c7" }}>
                🤖
              </div>
              <h3
                style={{
                  fontSize: "1.25rem",
                  fontWeight: "600",
                  marginBottom: "0.5rem",
                  color: "#0f172a",
                }}
              >
                AI Pre-Summary
              </h3>
              <p style={{ color: "#64748b", lineHeight: "1.6" }}>
                Speak your symptoms in Hindi or English. Our AI creates a
                structured clinical summary for your doctor to review before
                consultation.
              </p>
            </div>
          </div>
        </section>

        {/* CTA Section */}
        <section
          style={{
            padding: "4rem 2rem",
            textAlign: "center",
            backgroundColor: "#f1f5f9",
          }}
        >
          <h2
            style={{
              fontSize: "2rem",
              fontWeight: "bold",
              marginBottom: "1rem",
              color: "#0f172a",
            }}
          >
            Ready to Take Control of Your Health Data?
          </h2>
          <p
            style={{
              fontSize: "1.125rem",
              color: "#64748b",
              marginBottom: "2rem",
              maxWidth: "600px",
              margin: "0 auto 2rem auto",
            }}
          >
            Join CareSetu today and experience secure, consent-based health
            record management.
          </p>
          <Link href="/login" style={ctaButtonStyle}>
            Get Started
          </Link>
        </section>
      </main>

      {/* Footer */}
      <footer
        style={{
          padding: "2rem",
          textAlign: "center",
          backgroundColor: "#ffffff",
          borderTop: "1px solid #e2e8f0",
          color: "#64748b",
        }}
      >
        <p>&copy; 2026 CareSetu. All rights reserved.</p>
      </footer>
    </div>
  );
}
