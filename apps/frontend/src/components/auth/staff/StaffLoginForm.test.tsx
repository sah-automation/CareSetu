// PHASE-2.6 T10 (#201): staff login card behavior - MFA slot inertness, the
// show/hide toggle, and honest submit feedback (done-verify suite).

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { STRINGS } from "@/lib/i18n/dictionaries";

import { StaffLoginForm } from "./StaffLoginForm";

afterEach(cleanup);

const t = STRINGS.en.staffAuth.login;

function fill(valid: boolean) {
  fireEvent.change(screen.getByTestId("staff-email"), {
    target: { value: valid ? "dr.sharma@example.com" : "not-an-email" },
  });
  fireEvent.change(screen.getByTestId("staff-password"), {
    target: { value: valid ? "secret" : "" },
  });
}

describe("StaffLoginForm", () => {
  it("renders the email + password composition without any role picker", () => {
    render(<StaffLoginForm />);
    expect(screen.getByTestId("staff-email")).toBeInTheDocument();
    expect(screen.getByTestId("staff-password")).toBeInTheDocument();
    // §4.2: no role picker on the page, ever.
    expect(
      screen.queryByRole("button", { name: /doctor|lab|chemist/i }),
    ).not.toBeInTheDocument();
  });

  it("keeps the forgot-password link as a placeholder", () => {
    render(<StaffLoginForm />);
    const link = screen.getByTestId("forgot-password");
    expect(link).toHaveTextContent(t.forgotPassword);
  });

  it("does not render the MFA slot at all when nothing flags enrollment", () => {
    render(<StaffLoginForm />);
    expect(screen.queryByTestId("mfa-slot")).not.toBeInTheDocument();
  });

  it("renders the slot only-inert when enrollment is locally indicated", () => {
    render(<StaffLoginForm mfaEnrolled />);
    const slot = screen.getByTestId("mfa-slot");
    expect(slot).toHaveAttribute("aria-disabled", "true");
    const input = screen.getByTestId("mfa-input");
    expect(input).toBeDisabled();
    // The slot copy itself names where it activates.
    expect(slot).toHaveTextContent(/Phase 5/);
  });

  it("never submits a functional MFA step even when enrolled", () => {
    render(<StaffLoginForm mfaEnrolled />);
    fill(true);
    fireEvent.click(screen.getByTestId("staff-submit"));
    // Still the honest Phase 5 outcome - enrollment never unlocks anything.
    expect(screen.getByTestId("staff-phase5-notice")).toBeInTheDocument();
  });

  it("toggles password visibility through the labeled control", () => {
    render(<StaffLoginForm />);
    const input = screen.getByTestId("staff-password");
    const toggle = screen.getByTestId("password-toggle");
    expect(input).toHaveAttribute("type", "password");
    fireEvent.click(toggle);
    expect(input).toHaveAttribute("type", "text");
    expect(toggle).toHaveAttribute("aria-label", t.hidePassword);
    fireEvent.click(toggle);
    expect(input).toHaveAttribute("type", "password");
    expect(toggle).toHaveAttribute("aria-label", t.showPassword);
  });

  it("validates a field on blur without summoning the submit summary", () => {
    render(<StaffLoginForm />);
    fireEvent.blur(screen.getByTestId("staff-email"));
    expect(screen.getByTestId("staff-email-error")).toHaveTextContent(
      t.emailInvalid,
    );
    // Blur alone never claims a failed submit.
    expect(screen.queryByTestId("staff-form-summary")).not.toBeInTheDocument();
  });

  it("clears a field error once blur sees a valid value", () => {
    render(<StaffLoginForm />);
    const email = screen.getByTestId("staff-email");
    fireEvent.blur(email);
    fireEvent.change(email, { target: { value: "dr.sharma@example.com" } });
    fireEvent.blur(email);
    expect(screen.queryByTestId("staff-email-error")).not.toBeInTheDocument();
  });

  it("summarizes invalid submits with a count and focuses the first bad field", () => {
    render(<StaffLoginForm />);
    fireEvent.click(screen.getByTestId("staff-submit"));
    const summary = screen.getByTestId("staff-form-summary");
    expect(summary).toHaveTextContent(t.summaryTitle(2));
    expect(document.activeElement?.id).toBe("staff-email");
  });

  it("focuses the password field when only it is invalid", () => {
    render(<StaffLoginForm />);
    fireEvent.change(screen.getByTestId("staff-email"), {
      target: { value: "dr.sharma@example.com" },
    });
    fireEvent.click(screen.getByTestId("staff-submit"));
    expect(document.activeElement?.id).toBe("staff-password");
  });

  it("submits honestly: names Phase 5, fabricates no success state", () => {
    render(<StaffLoginForm />);
    fill(true);
    fireEvent.click(screen.getByTestId("staff-submit"));
    const notice = screen.getByRole("status");
    expect(notice).toHaveTextContent(t.phase5Notice);
    expect(notice).toHaveTextContent(/Phase 5/);
    // No success banner exists anywhere to fake.
    expect(screen.queryByTestId("staff-login-success")).not.toBeInTheDocument();
  });

  it("clears a previous submit notice when validation fails again", () => {
    render(<StaffLoginForm />);
    fill(true);
    fireEvent.click(screen.getByTestId("staff-submit"));
    expect(screen.getByTestId("staff-phase5-notice")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("staff-email"), {
      target: { value: "" },
    });
    fireEvent.click(screen.getByTestId("staff-submit"));
    expect(screen.queryByTestId("staff-phase5-notice")).not.toBeInTheDocument();
    expect(screen.getByTestId("staff-form-summary")).toBeInTheDocument();
  });
});
