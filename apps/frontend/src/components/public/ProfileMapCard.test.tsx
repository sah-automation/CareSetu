import { describe, expect, test, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

import { LangProvider } from "@/lib/i18n/LangContext";
import { ProfileMapCard } from "./ProfileMapCard";

afterEach(() => cleanup());

function renderCard(props: Parameters<typeof ProfileMapCard>[0] = {}) {
  return render(
    <LangProvider>
      <ProfileMapCard {...props} />
    </LangProvider>,
  );
}

describe("ProfileMapCard", () => {
  test("renders the heading and an embedded map", () => {
    renderCard({
      mode: "doctor",
      locality: "Medininagar Road",
      city: "Daltonganj",
      state: null,
      pincode: "826001",
    });

    expect(
      screen.getByRole("heading", { name: /Location & directions/i }),
    ).toBeInTheDocument();
    const embed = screen.getByTestId("profile-map-embed");
    expect(embed.src).toContain("maps.google.com/maps");
    expect(embed.src).toContain("output=embed");
  });

  test("queries the declared address and shows it beneath the frame", () => {
    renderCard({
      mode: "lab",
      locality: "Medininagar Road",
      city: "Daltonganj",
      state: null,
      pincode: "826001",
    });

    const embed = screen.getByTestId("profile-map-embed");
    expect(embed.src).toContain("Medininagar%20Road");
    expect(
      screen.getByText(/Medininagar Road, Daltonganj, 826001/),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("profile-map-empty")).not.toBeInTheDocument();
  });

  test("falls back to the static coordinates when nothing is declared", () => {
    renderCard({
      mode: "lab",
      locality: null,
      city: null,
      state: null,
      pincode: null,
    });

    const embed = screen.getByTestId("profile-map-embed");
    expect(embed.src).toContain("23.8388%2C84.0966");
    expect(screen.getByTestId("profile-map-empty")).toHaveTextContent(
      /No address declared yet/i,
    );
  });

  test("renders drive, walk, transit and open-map links", () => {
    renderCard({
      mode: "chemist",
      locality: "Main Road",
      city: "Daltonganj",
      state: null,
      pincode: "826001",
    });

    expect(screen.getByTestId("profile-map-directions")).toHaveAttribute(
      "aria-label",
      "Get directions - Drive",
    );
    expect(screen.getByTestId("profile-map-walking")).toBeInTheDocument();
    expect(screen.getByTestId("profile-map-transit")).toBeInTheDocument();
    expect(screen.getByTestId("profile-map-open")).toHaveAttribute(
      "aria-label",
      "Open map",
    );
    for (const testId of [
      "profile-map-directions",
      "profile-map-walking",
      "profile-map-transit",
      "profile-map-open",
    ]) {
      expect(screen.getByTestId(testId)).toHaveAttribute("target", "_blank");
    }
  });

  test("uses the doctor anchor for a doctor profile", () => {
    renderCard({
      mode: "doctor",
      locality: null,
      city: null,
      state: null,
      pincode: null,
    });
    expect(screen.getByTestId("profile-map-embed").src).toContain(
      "23.8450%2C84.0900",
    );
  });
});
