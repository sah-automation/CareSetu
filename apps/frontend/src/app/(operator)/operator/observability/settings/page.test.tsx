// #747: the Settings destination is a placeholder shell on purpose. These
// tests pin the shell itself and the Batch 2 boundary: no AI configuration,
// notification configuration, feature flags or user management until that
// surface ships.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ObservabilitySettingsPage from "./page";

describe("ObservabilitySettingsPage (#747)", () => {
  it("renders the placeholder shell behind the Settings destination", () => {
    render(<ObservabilitySettingsPage />);

    expect(screen.getByTestId("page-header")).toHaveTextContent("Settings");
    expect(screen.getByTestId("empty-state")).toBeInTheDocument();
  });

  it("carries none of the Batch 2 configuration surfaces", () => {
    const { container } = render(<ObservabilitySettingsPage />);

    // The shell has a header and an empty state and nothing else: no forms, no
    // inputs and no interactive controls of any kind (a role query would miss
    // an unlabelled <form>).
    expect(container.querySelector("form")).toBeNull();
    expect(
      container.querySelector("input, select, textarea, button"),
    ).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
  });
});
