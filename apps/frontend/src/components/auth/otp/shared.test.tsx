// #571: the contract for the three capabilities the shared sign-in atoms gained
// so the partner code step could be rebuilt on them without a mass rewrite of
// the staff suite (#572):
//
//  1. `CountdownRing`, moved here from the patient wizard so both wizards share
//     one ring.
//  2. A `testId` hook on every atom an existing staff selector already resolves
//     to. The hook has to land on the *same element the selector resolves to
//     today*, or #572 would have to rewrite the assertions - `partner-otp` in
//     particular sits on the hidden `<input>`, not the `.otpWrap` div.
//  3. `PrimaryButton`'s button-type passthrough. The ring and the hooks are
//     visible; this one is not, and it is the reason this ticket exists. Enter
//     -to-verify works today through native implicit form submission, not a key
//     handler (there is no Enter handler anywhere under `components/auth/**`),
//     and every one of the staff suite's submit sites drives the control with
//     `fireEvent.click`, so a button that quietly stopped being `type="submit"`
//     would break Enter in a real browser while the whole suite stayed green.

import { readFileSync } from "node:fs";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  CountdownRing,
  EditLinkButton,
  ErrorMessage,
  GhostButton,
  NoticeMessage,
  OtpInput,
  PrimaryButton,
} from "./shared";

// Indirection, as in variantB's CSS contract test: Vite statically rewrites a
// literal `new URL("./x", import.meta.url)` into an asset URL, which stops the
// read from hitting the filesystem.
const here = (rel: string) => new URL(rel, import.meta.url);

afterEach(cleanup);

describe("CountdownRing", () => {
  it("renders the remaining time as m:ss", () => {
    render(<CountdownRing seconds={245} />);
    expect(screen.getByText("4:05")).toBeInTheDocument();
  });

  it("renders the full TTL as 5:00 and the last minute as 1:00", () => {
    const { unmount } = render(<CountdownRing seconds={300} />);
    expect(screen.getByText("5:00")).toBeInTheDocument();
    unmount();

    render(<CountdownRing seconds={60} />);
    expect(screen.getByText("1:00")).toBeInTheDocument();
  });

  it("keeps the wheel decorative - the timer is not announced", () => {
    // The ring was `aria-hidden` in the patient wizard and stays that way: the
    // countdown is duplicated as visible text by the callers' own copy, so
    // exposing it here would double-announce. Pinned so a future "improvement"
    // cannot land unremarked.
    const { container } = render(<CountdownRing seconds={245} />);
    const wheel = container.querySelector("[aria-hidden='true']");
    expect(wheel).not.toBeNull();
    expect(wheel?.querySelector("svg")).not.toBeNull();
  });

  it("is the ring the patient wizard renders, not a second copy of it", () => {
    // The patient suite asserts on visible text and roles and holds zero
    // test-ids, so it cannot notice that the wizard grew its own private ring
    // again. The only assertion that can is this one, and it is a source-level
    // rule for the same reason `otpShared.module.test.ts` is a rule about CSS
    // text: the thing being pinned is a module-graph fact, not a render. The
    // match is scoped to the import statement so that a mention of the name in
    // a comment cannot satisfy it.
    const source = readFileSync(here("./PatientAuthWizard.tsx"), "utf8");
    const atomImport = source.match(/import \{[^}]*\} from "\.\/shared";/)?.[0];
    expect(atomImport).toBeDefined();
    expect(atomImport).toMatch(/\bCountdownRing\b/);
    expect(source).not.toMatch(/function CountdownRing/);
  });

  it("carries a hook on the span that holds the seconds", () => {
    // `partner-countdown` is the one staff selector this atom owns. It has to
    // sit on the element that renders the digits, which is the .ringTime span -
    // the wrapper is aria-hidden decoration.
    render(<CountdownRing seconds={245} testId="partner-countdown" />);
    const timer = screen.getByTestId("partner-countdown");
    expect(timer.tagName).toBe("SPAN");
    expect(timer).toHaveTextContent("4:05");
    expect(timer.closest("[aria-hidden='true']")).not.toBeNull();
  });
});

describe("atom test-hooks", () => {
  it("'partner-otp' lands on the hidden input, not the box wrapper", () => {
    render(
      <OtpInput
        testId="partner-otp"
        label="Verification code"
        value="12"
        onChange={() => {}}
      />,
    );
    const input = screen.getByTestId("partner-otp");
    expect(input.tagName).toBe("INPUT");
    // The wrapper is the click-to-focus box row; a hook there would leave the
    // staff suite's `fireEvent.change` driving a div.
    expect(input.parentElement).not.toHaveAttribute("data-testid");
  });

  it("'partner-error' lands on the alert paragraph and renders nothing for a null message", () => {
    const { rerender, container } = render(
      <ErrorMessage testId="partner-error" message="Wrong code." />,
    );
    const alert = screen.getByTestId("partner-error");
    expect(alert.tagName).toBe("P");
    expect(alert).toHaveAttribute("role", "alert");
    expect(alert).toHaveTextContent("Wrong code.");

    rerender(<ErrorMessage testId="partner-error" message={null} />);
    expect(screen.queryByTestId("partner-error")).not.toBeInTheDocument();
    expect(container).toBeEmptyDOMElement();
  });

  it("'partner-demo-banner' lands on the notice paragraph and keeps role='status'", () => {
    // The staff step's demo banner is a `<div role="status">` today. All four
    // of its assertions are `toHaveTextContent`, so swapping in a role-less
    // `NoticeMessage` would drop the announcement with a green suite - the role
    // is therefore part of the atom's contract, not an accident of the caller.
    render(
      <NoticeMessage
        testId="partner-demo-banner"
        role="status"
        message="Demo code 123456"
      />,
    );
    const banner = screen.getByTestId("partner-demo-banner");
    expect(banner.tagName).toBe("P");
    expect(banner).toHaveAttribute("role", "status");
    expect(banner).toHaveTextContent("Demo code 123456");
  });

  it("'partner-notice' renders a role-less paragraph by default", () => {
    // The patient wizard's notice carries no role; defaulting one in would be a
    // user-visible change on a surface this ticket must not touch.
    render(<NoticeMessage testId="partner-notice" message="Code sent." />);
    expect(screen.getByTestId("partner-notice")).not.toHaveAttribute("role");
  });

  it("'partner-resend' lands on the resend button and keeps its disabled state", () => {
    const onClick = vi.fn();
    render(
      <GhostButton testId="partner-resend" onClick={onClick} disabled>
        Resend
      </GhostButton>,
    );
    const button = screen.getByTestId("partner-resend");
    expect(button.tagName).toBe("BUTTON");
    expect(button).toBeDisabled();

    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("'staff-submit' lands on the primary button and keeps the pending gate", () => {
    const onClick = vi.fn();
    render(
      <PrimaryButton testId="staff-submit" onClick={onClick} pending>
        Verify
      </PrimaryButton>,
    );
    const button = screen.getByTestId("staff-submit");
    expect(button.tagName).toBe("BUTTON");
    expect(button).toBeDisabled();
  });

  it("'partner-edit-number' lands on the link-style edit button", () => {
    const onClick = vi.fn();
    render(
      <EditLinkButton testId="partner-edit-number" onClick={onClick}>
        Change number
      </EditLinkButton>,
    );
    const button = screen.getByTestId("partner-edit-number");
    expect(button.tagName).toBe("BUTTON");
    // Inside a form it must not submit on its own; the wizard's own raw button
    // was `type="button"`.
    expect(button).toHaveAttribute("type", "button");
    fireEvent.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("'partner-edit-number' keeps the busy-disable its raw button had", () => {
    // The staff step disables this control while the partner request is in
    // flight. An atom without the prop would let #572's swap re-enable it
    // mid-request, with nothing in the suite to notice.
    const onClick = vi.fn();
    const { rerender } = render(
      <EditLinkButton testId="partner-edit-number" onClick={onClick} disabled>
        Change number
      </EditLinkButton>,
    );
    const button = screen.getByTestId("partner-edit-number");
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();

    rerender(
      <EditLinkButton testId="partner-edit-number" onClick={onClick}>
        Change number
      </EditLinkButton>,
    );
    expect(screen.getByTestId("partner-edit-number")).not.toBeDisabled();
  });

  it("emits no data-testid on any atom that was not given one", () => {
    // The guard on "no user-visible change": an atom that defaulted its hook
    // would put a test id in the patient wizard's DOM.
    const { container } = render(
      <>
        <OtpInput label="Verification code" value="" onChange={() => {}} />
        <ErrorMessage message="Wrong code." />
        <NoticeMessage message="Code sent." />
        <PrimaryButton>Verify</PrimaryButton>
        <GhostButton onClick={() => {}}>Resend</GhostButton>
        <EditLinkButton onClick={() => {}}>Change number</EditLinkButton>
        <CountdownRing seconds={245} />
      </>,
    );
    expect(container.querySelector("[data-testid]")).toBeNull();
  });
});

describe("PrimaryButton button type", () => {
  it("defaults to type='button' so no existing call site becomes a submit", () => {
    render(<PrimaryButton>Verify</PrimaryButton>);
    expect(screen.getByRole("button")).toHaveAttribute("type", "button");
  });

  it("renders type='submit' when the caller asks for it", () => {
    render(<PrimaryButton type="submit">Verify</PrimaryButton>);
    expect(screen.getByRole("button")).toHaveAttribute("type", "submit");
  });

  // The regression this passthrough exists to prevent.
  //
  // Enter-to-verify rides on native implicit form submission: per the HTML
  // spec, Enter in a form's field activates the form's *default button*, which
  // is the first button whose type is `submit`. So the branch that matters is
  // "is this button `type="submit"`?", and the branch that broke the surface
  // when the partner step swapped its control for a `type="button"` atom is
  // exactly that. The staff suite cannot see it: all twelve of its submit
  // sites drive the control with `fireEvent.click`, and a click on a
  // non-submitting button fires no submit event.
  //
  // jsdom does not implement the spec's "default button" step for
  // `requestSubmit()`, so pressing Enter cannot be driven directly here. What
  // jsdom does enforce is the property implicit submission rests on - a
  // button's activation submits the form if and only if it is a submit button
  // - and that is what these two assertions pin.
  it("participates in form submission only when type='submit'", () => {
    const onSubmit = vi.fn((e: React.FormEvent) => e.preventDefault());
    const { container, unmount } = render(
      <form onSubmit={onSubmit}>
        <input aria-label="Verification code" />
        <PrimaryButton type="submit">Verify</PrimaryButton>
      </form>,
    );
    const form = container.querySelector("form") as HTMLFormElement;
    const button = screen.getByRole("button");

    fireEvent.click(button);
    expect(onSubmit).toHaveBeenCalledTimes(1);

    onSubmit.mockClear();
    expect(() => form.requestSubmit(button)).not.toThrow();
    expect(onSubmit).toHaveBeenCalledTimes(1);
    unmount();

    onSubmit.mockClear();
    render(
      <form onSubmit={onSubmit}>
        <input aria-label="Verification code" />
        <PrimaryButton>Verify</PrimaryButton>
      </form>,
    );
    const nonSubmitting = screen.getByRole("button");

    fireEvent.click(nonSubmitting);
    expect(onSubmit).not.toHaveBeenCalled();
    expect(() => form.requestSubmit(nonSubmitting)).toThrow(TypeError);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits the form when the field is submitted directly", () => {
    const onSubmit = vi.fn((e: React.FormEvent) => e.preventDefault());
    const { container } = render(
      <form onSubmit={onSubmit}>
        <PrimaryButton type="submit">Verify</PrimaryButton>
      </form>,
    );
    fireEvent.submit(container.querySelector("form") as HTMLFormElement);
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("still fires onClick, and does not submit the form on click by default", () => {
    const onClick = vi.fn();
    const onSubmit = vi.fn((e: React.FormEvent) => e.preventDefault());
    render(
      <form onSubmit={onSubmit}>
        <PrimaryButton onClick={onClick}>Verify</PrimaryButton>
      </form>,
    );
    fireEvent.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(onSubmit).not.toHaveBeenCalled();
  });
});

describe("OtpInput stays a controlled single input", () => {
  it("reports the raw six-digit draft upwards", () => {
    // `partner-otp` is driven by `fireEvent.change` seventeen times in the staff
    // suite, so the hook has to be on an input that actually fires onChange.
    function Harness() {
      const [value, setValue] = useState("");
      return (
        <OtpInput
          testId="partner-otp"
          label="Verification code"
          value={value}
          onChange={setValue}
        />
      );
    }
    render(<Harness />);
    fireEvent.change(screen.getByTestId("partner-otp"), {
      target: { value: "123456" },
    });
    expect(screen.getByTestId("partner-otp")).toHaveValue("123456");
    expect(screen.getByText("6")).toBeInTheDocument();
  });
});

describe("#576: the code field's accessible name and error wiring are the caller's", () => {
  // #572 rebuilt the partner code step on this atom and, in doing so, gave the
  // field a hardcoded English `aria-label` that takes precedence over the
  // dictionary label the step renders beside it. An `aria-label` outranks the
  // wrapping `<label>` in the accessible-name computation, so a partner reading
  // the step in Hindi saw "वेरिफिकेशन कोड" on screen and heard "Verification
  // code" - the bilingual parity rule the whole string dictionary exists to
  // enforce, broken by the atom the step was moved onto. The same swap dropped
  // the `aria-invalid` and `aria-describedby` the raw input carried, and the
  // staff suite has no selector that notices either loss.
  //
  // The Hindi value is the load-bearing half. Asserting the English string would
  // pass against the hardcoded literal, which is exactly the defect.
  it("names the field from the caller's string, in either locale", () => {
    const { unmount } = render(
      <OtpInput label="वेरिफिकेशन कोड" value="" onChange={() => {}} />,
    );
    expect(screen.getByLabelText("वेरिफिकेशन कोड")).toBeInTheDocument();
    unmount();

    render(<OtpInput label="Verification code" value="" onChange={() => {}} />);
    expect(screen.getByLabelText("Verification code")).toBeInTheDocument();
  });

  it("carries the invalid state and the error association the caller asks for", () => {
    render(
      <OtpInput
        label="Verification code"
        value=""
        onChange={() => {}}
        invalid
        describedBy="partner-error"
      />,
    );
    const input = screen.getByLabelText("Verification code");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAttribute("aria-describedby", "partner-error");
  });

  it("claims neither when the caller has no error to report", () => {
    render(<OtpInput label="Verification code" value="" onChange={() => {}} />);
    const input = screen.getByLabelText("Verification code");
    expect(input).not.toHaveAttribute("aria-invalid");
    expect(input).not.toHaveAttribute("aria-describedby");
  });

  // A source-level rule, not a DOM one: jsdom resolves no stylesheet and no
  // dictionary, so a hardcoded literal and a dictionary-driven prop are
  // indistinguishable in the rendered tree except by the locale assertion above.
  // This pins the shape of the fix, in the same shape the parity gate and the
  // token gate use for the same reason.
  it("carries no literal accessible name of its own", () => {
    const source = readFileSync(here("shared.tsx"), "utf8");
    expect(source).not.toMatch(/aria-label="Verification code"/);
    expect(source).not.toMatch(/aria-label="OTP"/);
  });
});
