import { render, screen, cleanup } from "@testing-library/react";
import { describe, it, expect, afterEach } from "vitest";

// #600 - the Card primitive adopted over the #193 design tokens. Every part is
// a plain div with no state, so what is worth pinning is that the parts nest in
// document order and that the surface resolves to tokens.
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
} from "./card";

afterEach(() => {
  cleanup();
});

describe("Card", () => {
  it("renders its parts in order inside one surface", () => {
    render(
      <Card data-testid="card">
        <CardHeader>
          <CardTitle>Practice</CardTitle>
          <CardDescription>Where patients see you</CardDescription>
        </CardHeader>
        <CardContent>Body</CardContent>
        <CardFooter>Actions</CardFooter>
      </Card>,
    );

    const card = screen.getByTestId("card");
    expect(card.tagName).toBe("DIV");
    // Every part is a descendant of the card surface, in document order.
    expect(Array.from(card.children).map((child) => child.textContent)).toEqual(
      ["PracticeWhere patients see you", "Body", "Actions"],
    );
  });

  it("resolves its surface, edge, radius and elevation through tokens", () => {
    render(<Card data-testid="card" />);

    const className = screen.getByTestId("card").className;
    // The four #193 tokens every hand-rolled card in the app already uses.
    expect(className).toContain("rounded-lg");
    expect(className).toContain("border-input");
    expect(className).toContain("bg-surface");
    expect(className).toContain("text-foreground");
    expect(className).toContain("shadow-card");
    // No stock radius or elevation step survived the bridge.
    expect(className).not.toContain("rounded-xl");
    expect(className).not.toContain(" shadow ");
  });

  it("merges caller className over the defaults", () => {
    render(<Card className="p-4 rounded-md" data-testid="card" />);

    const className = screen.getByTestId("card").className;
    expect(className).toContain("p-4");
    // tailwind-merge drops the conflicting default radius.
    expect(className).not.toContain("rounded-lg");
  });

  it("gives the header its own stacking gap and the content its inset", () => {
    render(
      <Card>
        <CardHeader data-testid="header" />
        <CardContent data-testid="content" />
        <CardFooter data-testid="footer" />
      </Card>,
    );

    expect(screen.getByTestId("header").className).toContain("p-6");
    expect(screen.getByTestId("content").className).toContain("pt-0");
    expect(screen.getByTestId("footer").className).toContain("flex");
  });
});
