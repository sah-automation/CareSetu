// PHASE-2.6 T09 (#200): suite for homepage section 5 - featured doctor
// cards. Covers both acceptance branches against a mocked fetch of the
// marked integration point (lib/directory/featured, gap G2): live verified
// cards when activated supply exists, and the honest "Directory launching
// soon" empty state when it does not - plus the loading and failure paths.
//
// #962: the card row is a horizontal scroll-snap carousel, so the suite also
// pins the ARIA list structure, the arrow buttons with their localised
// labels, the end-of-track disabled states (against mocked track
// dimensions), the card photo with its initials fallback, and the
// reduced-motion scroll behaviour.
//
// #965: the card renders the full prototype (homepage-resolved-v2 `.illus-card`)
// anatomy - video badge, ribbon, credentials, practice, specialty + years of
// experience, rating, facts, verified badge + distance, tags and the declared
// address - so the suite pins each of those rows too.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FeaturedDoctors } from "./FeaturedDoctors";
import type { FeaturedDoctor } from "@/lib/directory/featured";
import { getMockCardData, getMockRating } from "@/lib/directory/mockDisplay";
import {
  __resetLangForTests,
  LangProvider,
  useLang,
} from "@/lib/i18n/LangContext";

vi.mock("@/lib/directory/featured", () => ({
  fetchFeaturedDoctors: vi.fn(),
}));

vi.mock("@/lib/directory/usePartnerPhotoSource", () => ({
  usePartnerPhotoSource: vi.fn(() => ({ src: null, absent: false })),
}));

// Import after the mock declaration so the suite binds the mocked function.
import { fetchFeaturedDoctors } from "@/lib/directory/featured";
import { usePartnerPhotoSource } from "@/lib/directory/usePartnerPhotoSource";

const mockFetchFeatured = vi.mocked(fetchFeaturedDoctors);
const mockPhotoSource = vi.mocked(usePartnerPhotoSource);

const CARDS: FeaturedDoctor[] = [
  {
    id: 1,
    name: "Dr. A. Kumar",
    specialty: "General Physician",
    area: "Medininagar Rd",
    distance_km: 1.2,
    consultation_fee: 30000,
    photo_ref: "doctor/1/photo.jpg",
    clinic_name: null,
    experience_years: 12,
    languages: ["Hindi", "English"],
    address_line: "Medininagar Road",
    city: "Daltonganj",
  },
  {
    id: 2,
    name: "Dr. S. Devi",
    specialty: "Gynecologist",
    area: null,
    distance_km: 3.4,
    consultation_fee: null,
    photo_ref: null,
    clinic_name: "Seva Nursing Home",
    experience_years: null,
    languages: [],
    address_line: null,
    city: null,
  },
];

/** Shadow the track's layout numbers (jsdom has no layout engine). */
function mockTrackDimensions(
  track: HTMLElement,
  dims: { scrollWidth: number; clientWidth: number; scrollLeft?: number },
): void {
  Object.defineProperty(track, "scrollWidth", {
    configurable: true,
    value: dims.scrollWidth,
  });
  Object.defineProperty(track, "clientWidth", {
    configurable: true,
    value: dims.clientWidth,
  });
  Object.defineProperty(track, "scrollLeft", {
    configurable: true,
    writable: true,
    value: dims.scrollLeft ?? 0,
  });
}

/** jsdom ships no matchMedia, so the motion preference is stubbed per test. */
function stubMotionPreference(noPreference: boolean): void {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: (query: string) => ({
      matches: noPreference,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  });
}

/** jsdom has no layout either: pin the first card's measured width. */
function mockFirstCardWidth(track: HTMLElement, width: number): void {
  const [card] = within(track).getAllByRole("listitem");
  vi.spyOn(card, "getBoundingClientRect").mockReturnValue({
    width,
    height: 200,
    x: 0,
    y: 0,
    top: 0,
    right: width,
    bottom: 200,
    left: 0,
    toJSON: () => ({}),
  } as DOMRect);
}

beforeEach(() => {
  mockFetchFeatured.mockReset();
  mockPhotoSource.mockReset();
  mockPhotoSource.mockReturnValue({ src: null, absent: false });
  localStorage.clear();
  __resetLangForTests();
  document.documentElement.lang = "en";
});

afterEach(() => {
  delete (window as { matchMedia?: unknown }).matchMedia;
  cleanup();
});

describe("FeaturedDoctors (gap G2)", () => {
  it("shows skeletons while the integration point resolves", () => {
    mockFetchFeatured.mockReturnValue(new Promise(() => {}));
    render(<FeaturedDoctors />);

    expect(screen.getByTestId("featured-loading")).toBeInTheDocument();
    expect(screen.queryByTestId("empty-state")).not.toBeInTheDocument();
    expect(screen.queryByTestId("featured-cards")).not.toBeInTheDocument();
  });

  it("renders live verified cards when activated supply exists", async () => {
    mockFetchFeatured.mockResolvedValue(CARDS);
    render(<FeaturedDoctors />);

    await waitFor(() =>
      expect(screen.getByTestId("featured-cards")).toBeInTheDocument(),
    );
    expect(screen.getByText("Dr. A. Kumar")).toBeInTheDocument();
    expect(screen.getByText("Dr. S. Devi")).toBeInTheDocument();
    // Only activated providers are ever returned, so every card shows the
    // truthful verified indicator (FEAT-004 Rule 1 / FEAT-005). Meta joins
    // non-null parts only - the dropped `consultType` never renders, and a
    // card without an experience shows just its specialty.
    expect(screen.getAllByText("Verified")).toHaveLength(2);
    // #961/#965 card template: specialty joins the years of experience,
    // practice falls back to the locality when no clinic is declared,
    // distance comes from the payload, and the fee cell shows paise->rupees
    // only when the payload carried one.
    expect(
      screen.getByText("General Physician \u00b7 12 years experience"),
    ).toBeInTheDocument();
    expect(screen.getByText("Medininagar Rd")).toBeInTheDocument();
    expect(screen.getByText("1.2 km")).toBeInTheDocument();
    expect(screen.getByText("3.4 km")).toBeInTheDocument();
    expect(screen.getByText("Gynecologist")).toBeInTheDocument();
    expect(screen.getByText(/₹300/)).toBeInTheDocument();
    expect(screen.getByText("consult")).toBeInTheDocument();
    // No fake cards means no empty state either.
    expect(screen.queryByTestId("empty-state")).not.toBeInTheDocument();
    // Cards target provider profiles; view-all pre-seeds the directory.
    // #962 gives each card role="listitem" (the carousel contract), so the
    // deep link is asserted on the card element - it is still an <a href>.
    expect(
      screen.getAllByRole("listitem").map((card) => card.getAttribute("href")),
    ).toEqual(["/providers/1", "/providers/2"]);
    expect(
      screen.getByRole("link", { name: "View all doctors" }),
    ).toHaveAttribute("href", "/directory?type=doctor");
  });

  it("renders the full prototype card anatomy (#965)", async () => {
    mockFetchFeatured.mockResolvedValue(CARDS);
    render(<FeaturedDoctors />);

    await waitFor(() =>
      expect(screen.getByTestId("featured-cards")).toBeInTheDocument(),
    );

    const cards = screen.getAllByRole("listitem");
    expect(cards).toHaveLength(2);
    const first = within(cards[0]);
    const second = within(cards[1]);

    // Card 1: video badge, ribbon, credentials, practice (locality when no
    // clinic), specialty + experience, mock rating, facts, mode tag with the
    // real declared languages, and the declared address line.
    const mock1 = getMockCardData(1, "doctor");
    const rating1 = getMockRating(1);
    if (mock1.videoBadge) {
      expect(
        first.getByTestId("featured-card-video-badge"),
      ).toBeInTheDocument();
    } else {
      expect(
        first.queryByTestId("featured-card-video-badge"),
      ).not.toBeInTheDocument();
    }
    if (mock1.highlightRibbon) {
      expect(first.getByTestId("featured-card-ribbon")).toHaveTextContent(
        mock1.highlightRibbon,
      );
    }
    expect(first.getByTestId("featured-card-practice")).toHaveTextContent(
      "Medininagar Rd",
    );
    expect(
      first.getByText("General Physician \u00b7 12 years experience"),
    ).toBeInTheDocument();
    expect(first.getByTestId("featured-card-rating")).toHaveTextContent(
      `${rating1.stars.toFixed(1)} (${rating1.reviewCount} reviews)`,
    );
    expect(
      first
        .getAllByTestId("featured-card-fact")
        .map((fact) => fact.textContent),
    ).toEqual(mock1.facts.map((fact) => fact.label));
    expect(
      first.getAllByTestId("featured-card-tag").map((tag) => tag.textContent),
    ).toEqual([mock1.tags[0].label, "Hindi, English"]);
    expect(first.getByTestId("featured-card-location")).toHaveTextContent(
      "Medininagar Road, Daltonganj",
    );

    // Card 2: clinic practice, no experience suffix, no address row, and the
    // mock language tag standing in for the undeclared languages.
    const mock2 = getMockCardData(2, "doctor");
    expect(second.getByTestId("featured-card-practice")).toHaveTextContent(
      "Seva Nursing Home",
    );
    expect(second.getByText("Gynecologist")).toBeInTheDocument();
    expect(
      second.queryByTestId("featured-card-location"),
    ).not.toBeInTheDocument();
    expect(
      second.getAllByTestId("featured-card-tag").map((tag) => tag.textContent),
    ).toEqual(mock2.tags.map((tag) => tag.label));
  });

  it("renders the honest launching-soon empty state when supply is empty", async () => {
    mockFetchFeatured.mockResolvedValue([]);
    render(<FeaturedDoctors />);

    expect(await screen.findByTestId("empty-state")).toBeInTheDocument();
    expect(
      screen.getByText("Directory launching soon in Daltonganj"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Get started as a patient" }),
    ).toHaveAttribute("href", "/login");
    expect(screen.queryByTestId("featured-cards")).not.toBeInTheDocument();
  });

  it("degrades a failed fetch to the honest empty state", async () => {
    mockFetchFeatured.mockRejectedValue(new Error("network down"));
    render(<FeaturedDoctors />);

    expect(await screen.findByTestId("empty-state")).toBeInTheDocument();
    expect(screen.queryByTestId("featured-cards")).not.toBeInTheDocument();
  });
});

describe("FeaturedDoctors carousel (#962)", () => {
  it("announces the track as a list of cards and keeps the swipe hint", async () => {
    mockFetchFeatured.mockResolvedValue(CARDS);
    render(<FeaturedDoctors />);

    await waitFor(() =>
      expect(screen.getByTestId("featured-cards")).toBeInTheDocument(),
    );

    const track = screen.getByRole("list", { name: "Featured doctors" });
    expect(within(track).getAllByRole("listitem")).toHaveLength(2);
    expect(
      screen.getByText("Swipe or use the arrows to see more"),
    ).toBeInTheDocument();
    // Loading and empty states never coexist with the track.
    expect(screen.queryByTestId("featured-loading")).not.toBeInTheDocument();
    expect(screen.queryByTestId("empty-state")).not.toBeInTheDocument();
  });

  it("exposes focusable prev/next arrows with localised labels", async () => {
    mockFetchFeatured.mockResolvedValue(CARDS);
    render(<FeaturedDoctors />);

    await waitFor(() =>
      expect(
        screen.getByRole("list", { name: "Featured doctors" }),
      ).toBeInTheDocument(),
    );

    const prev = screen.getByRole("button", { name: "Scroll cards left" });
    const next = screen.getByRole("button", { name: "Scroll cards right" });
    // Keyboard users reach both controls through the tab order as native
    // buttons; the label is the localised i18n string, not an icon title.
    expect(prev).toHaveAttribute("type", "button");
    expect(next).toHaveAttribute("type", "button");
    expect(prev).not.toHaveAttribute("aria-hidden");
    expect(next).not.toHaveAttribute("aria-hidden");
  });

  it("disables both arrows while the track has nothing to scroll", async () => {
    mockFetchFeatured.mockResolvedValue(CARDS);
    render(<FeaturedDoctors />);

    const track = await screen.findByTestId("featured-cards");
    mockTrackDimensions(track, { scrollWidth: 660, clientWidth: 660 });
    fireEvent.scroll(track);

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Scroll cards left" }),
      ).toBeDisabled();
      expect(
        screen.getByRole("button", { name: "Scroll cards right" }),
      ).toBeDisabled();
    });
  });

  it("disables prev at the start and next once scrolled to the end", async () => {
    mockFetchFeatured.mockResolvedValue(CARDS);
    render(<FeaturedDoctors />);

    const track = await screen.findByTestId("featured-cards");
    mockTrackDimensions(track, { scrollWidth: 1000, clientWidth: 400 });
    fireEvent.scroll(track);

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Scroll cards left" }),
      ).toBeDisabled();
      expect(
        screen.getByRole("button", { name: "Scroll cards right" }),
      ).not.toBeDisabled();
    });

    // 1000 - 400 - 2 is the prototype's end tolerance.
    mockTrackDimensions(track, {
      scrollWidth: 1000,
      clientWidth: 400,
      scrollLeft: 600,
    });
    fireEvent.scroll(track);

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Scroll cards left" }),
      ).not.toBeDisabled();
      expect(
        screen.getByRole("button", { name: "Scroll cards right" }),
      ).toBeDisabled();
    });
  });

  it("scrolls by one card on next, falling back to scrollLeft when scrollBy is missing", async () => {
    mockFetchFeatured.mockResolvedValue(CARDS);
    render(<FeaturedDoctors />);

    const track = await screen.findByTestId("featured-cards");
    mockTrackDimensions(track, { scrollWidth: 1000, clientWidth: 400 });
    fireEvent.scroll(track);
    mockFirstCardWidth(track, 330);

    // jsdom has no Element#scrollBy, so the component must move scrollLeft.
    const next = screen.getByRole("button", { name: "Scroll cards right" });
    await waitFor(() => expect(next).not.toBeDisabled());
    fireEvent.click(next);

    // First card width + the 1rem track gap.
    expect(track.scrollLeft).toBe(346);
    fireEvent.scroll(track);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Scroll cards left" }),
      ).not.toBeDisabled(),
    );
  });

  it("scrolls instantly when the visitor prefers reduced motion", async () => {
    stubMotionPreference(false);
    mockFetchFeatured.mockResolvedValue(CARDS);
    render(<FeaturedDoctors />);

    const track = await screen.findByTestId("featured-cards");
    mockTrackDimensions(track, { scrollWidth: 1000, clientWidth: 400 });
    fireEvent.scroll(track);
    mockFirstCardWidth(track, 330);
    const scrollBy = vi.fn();
    Object.defineProperty(track, "scrollBy", {
      configurable: true,
      value: scrollBy,
    });
    const next = screen.getByRole("button", { name: "Scroll cards right" });
    await waitFor(() => expect(next).not.toBeDisabled());

    fireEvent.click(next);

    expect(scrollBy).toHaveBeenCalledTimes(1);
    expect(scrollBy).toHaveBeenCalledWith(
      expect.objectContaining({ left: 346, behavior: "auto" }),
    );
  });

  it("scrolls smoothly when no reduced-motion preference is set", async () => {
    stubMotionPreference(true);
    mockFetchFeatured.mockResolvedValue(CARDS);
    render(<FeaturedDoctors />);

    const track = await screen.findByTestId("featured-cards");
    mockTrackDimensions(track, { scrollWidth: 1000, clientWidth: 400 });
    fireEvent.scroll(track);
    mockFirstCardWidth(track, 330);
    const scrollBy = vi.fn();
    Object.defineProperty(track, "scrollBy", {
      configurable: true,
      value: scrollBy,
    });
    const next = screen.getByRole("button", { name: "Scroll cards right" });
    await waitFor(() => expect(next).not.toBeDisabled());

    fireEvent.click(next);

    expect(scrollBy).toHaveBeenCalledWith(
      expect.objectContaining({ left: 346, behavior: "smooth" }),
    );
  });

  it("renders the profile photo when the payload carries one, initials otherwise", async () => {
    mockPhotoSource.mockImplementation((partnerId: number) =>
      partnerId === 1
        ? { src: "blob:photo-1", absent: false }
        : { src: null, absent: false },
    );
    mockFetchFeatured.mockResolvedValue(CARDS);
    render(<FeaturedDoctors />);

    await waitFor(() =>
      expect(screen.getByTestId("featured-cards")).toBeInTheDocument(),
    );

    // Photo source resolves through the same hook the directory card uses.
    expect(mockPhotoSource).toHaveBeenCalledWith(1, "doctor/1/photo.jpg");
    expect(mockPhotoSource).toHaveBeenCalledWith(2, null);

    const images = screen.getAllByRole("img");
    expect(images).toHaveLength(1);
    expect(images[0]).toHaveAttribute("alt", "Dr. A. Kumar");
    // The card without a photo falls back to its two-letter monogram.
    expect(screen.getByText("SD")).toBeInTheDocument();
  });

  it("renders the carousel copy in Hindi once the visitor toggles language", async () => {
    function LangSwitch() {
      const { setLang } = useLang();
      return (
        <button type="button" onClick={() => setLang("hi")}>
          to-hi
        </button>
      );
    }
    mockFetchFeatured.mockResolvedValue(CARDS);
    render(
      <LangProvider>
        <FeaturedDoctors />
        <LangSwitch />
      </LangProvider>,
    );

    await waitFor(() =>
      expect(
        screen.getByRole("list", { name: "Featured doctors" }),
      ).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("button", { name: "to-hi" }));

    expect(
      await screen.findByRole("button", { name: "कार्ड बाएँ स्क्रॉल करें" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("list", { name: "चुनिंदा डॉक्टर" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("और देखने के लिए स्वाइप करें या तीरों का उपयोग करें"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "कार्ड दाएँ स्क्रॉल करें" }),
    ).toBeInTheDocument();
  });
});
