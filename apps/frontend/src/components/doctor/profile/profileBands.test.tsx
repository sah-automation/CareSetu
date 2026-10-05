// PRD trace: FEAT-005 (Provider Profiles and Credential Display).
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useEffect, type ReactNode } from "react";

import { ProfileIdentityBand } from "./ProfileIdentityBand";
import { ProfileCredentialList } from "./ProfileCredentialList";
import { PROFILE_ANCHORS, ProfileSectionIndex } from "./ProfileSectionIndex";
import type { DoctorProfileView } from "@/lib/doctor/api";
import { STRINGS, type Lang } from "@/lib/i18n/dictionaries";
import { LangProvider, __resetLangForTests } from "@/lib/i18n/LangContext";

const t = STRINGS.en.doctorProfile;

function profile(
  overrides: Partial<DoctorProfileView> = {},
): DoctorProfileView {
  return {
    partner_id: 7,
    photo_ref: null,
    practice_name: "Asha Rao",
    clinic_name: "Asha Clinic",
    specialties: ["General Physician", "Paediatrics"],
    verified: true,
    practice_address: "Main Road",
    address_line: null,
    landmark: null,
    locality: null,
    city: null,
    pin_code: null,
    practice_latitude: 24.1957,
    practice_longitude: 85.3656,
    area: "Daltonganj",
    languages: [],
    experience_years: null,
    about: null,
    consultation_fee: null,
    consulting_days: [],
    consulting_hours: null,
    credentials: [],
    notification_preferences: {},
    ...overrides,
  };
}

// Nothing about the band needs transport, so the defaults are inert callbacks
// rather than mocks: a test that wants one to fire asks for it explicitly.
const noop = () => {};

function renderBand(overrides: Partial<DoctorProfileView> = {}) {
  return render(
    <ProfileIdentityBand
      profile={profile(overrides)}
      photoUrl={null}
      mediaAbsent={false}
      busy={false}
      failure={null}
      onPick={noop}
      onRemove={noop}
      onDismissFailure={noop}
    />,
  );
}

// The locale store is process-global, so a test that switches to Hindi would
// otherwise leave every later test in this file asserting English strings
// against Hindi markup. `cleanup` alone does not reset it.
afterEach(() => {
  cleanup();
  __resetLangForTests();
});

describe("ProfileIdentityBand", () => {
  it("makes the doctor's name the page's only h1 and the clinic the line beneath", () => {
    renderBand();

    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading).toHaveTextContent("Asha Rao");
    expect(screen.getByTestId("profile-clinic")).toHaveTextContent(
      "Asha Clinic",
    );
  });

  it("renders one chip per declared specialty", () => {
    renderBand();

    const chips = screen.getAllByTestId("profile-specialty");
    expect(chips.map((chip) => chip.textContent)).toEqual([
      "General Physician",
      "Paediatrics",
    ]);
    expect(screen.queryByTestId("profile-specialties-empty")).toBeNull();
  });

  it("names an empty selection instead of rendering a bare chip row", () => {
    renderBand({ specialties: [] });

    expect(screen.getByTestId("profile-specialties-empty")).toHaveTextContent(
      t.noSpecialtiesYet,
    );
  });

  it("ticks from the projection's own flag and nothing else", () => {
    // The tick is not derived here. A client that recomputed credential validity
    // to decide what to tick would be a second derivation site, and the two would
    // eventually disagree - which is the failure "tick gone = card gone" rules out.
    renderBand({ verified: true });
    expect(screen.getByTestId("profile-identity-verified")).toHaveTextContent(
      t.verified,
    );

    cleanup();

    renderBand({ verified: false });
    expect(screen.getByTestId("profile-identity-verified")).toHaveTextContent(
      t.notVerified,
    );
  });

  it("keeps the picker's camera control inside the band", () => {
    const onPick = vi.fn();
    const band = render(
      <ProfileIdentityBand
        profile={profile()}
        photoUrl={null}
        mediaAbsent={false}
        busy={false}
        failure={null}
        onPick={onPick}
        onRemove={noop}
        onDismissFailure={noop}
      />,
    );

    const upload = band.baseElement.querySelector(
      '[data-testid="profile-photo-upload"]',
    );
    // A control across the page from the face it replaces is the problem this
    // band exists to remove, so the button is inside the band by construction.
    expect(band.container.contains(upload)).toBe(true);
    // No photo yet, so it offers Upload and no Remove that cannot succeed.
    expect(upload).toHaveTextContent(t.photoUpload);
    expect(screen.queryByTestId("profile-photo-remove")).toBeNull();
  });

  it("offers Remove instead of a second Upload once a photo is stored", () => {
    renderBand({ photo_ref: "doctor/7/photo-1.enc" });

    expect(screen.getByTestId("profile-photo-upload")).toHaveTextContent(
      t.photoReplace,
    );
    expect(screen.getByTestId("profile-photo-remove")).toBeInTheDocument();
  });

  it("treats a ref the backend says has no bytes behind it as no photo", () => {
    // A set ref with nothing behind it offers Upload rather than a Remove that
    // cannot succeed - the "claim versus fact" rule the shared hook encodes.
    render(
      <ProfileIdentityBand
        profile={profile({ photo_ref: "doctor/7/photo-1.enc" })}
        photoUrl={null}
        mediaAbsent={true}
        busy={false}
        failure={null}
        onPick={noop}
        onRemove={noop}
        onDismissFailure={noop}
      />,
    );

    expect(screen.getByTestId("profile-photo-upload")).toHaveTextContent(
      t.photoUpload,
    );
    expect(screen.queryByTestId("profile-photo-remove")).toBeNull();
  });

  it("surfaces an upload failure with its trace id and no retry action", () => {
    render(
      <ProfileIdentityBand
        profile={profile()}
        photoUrl={null}
        mediaAbsent={false}
        busy={false}
        failure={{ traceId: "trace-9" }}
        onPick={noop}
        onRemove={noop}
        onDismissFailure={noop}
      />,
    );

    expect(screen.getByTestId("error-banner")).toHaveTextContent(t.photoFailed);
    expect(screen.getByTestId("error-banner-trace-id")).toHaveTextContent(
      "trace-9",
    );
    // No retry: a failed upload has no stored file to re-send, so the doctor
    // picks again from the button rather than re-sending nothing.
    expect(screen.queryByTestId("error-banner-retry")).toBeNull();
  });

  it("falls back through the name to the clinic to the page's own title", () => {
    // The h1 is the one element whose absence would leave a screen with no title
    // at all, so every one of these has to render something.
    renderBand({ practice_name: null });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Asha Clinic",
    );
    cleanup();

    renderBand({ practice_name: null, clinic_name: null });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      t.title,
    );
  });
});

// #623 (F15): the declared band's copy (#619) rendered in both locales.
//
// Every assertion above reads its expected string out of `STRINGS.en`, and that
// is this assertion pattern's blind spot rather than the band's: reading a string
// back out of the same dictionary entry the component reads it from proves the
// component is WIRED, not that the string is right. A Hindi entry copied from the
// English one, left empty, or never written passes all of them while shipping a
// page a Hindi-reading doctor cannot use. REQ-006 asks for equal-quality copy in
// both locales, and equal quality is not equal KEYS - key parity, which #617
// already asserts, is satisfied by a Hindi file full of English.
//
// So each string is asserted in BOTH locales, each one queried the way the band
// actually puts it on the page - some are visible text, some are accessible names
// on a non-text element, and two only render on a fallback path. Asserting them by
// a single generic `getByText` would have quietly dropped the aria-labelled ones,
// which is the failure mode this suite exists to remove.
describe("declared band copy in both locales (#619, #623 F15)", () => {
  type Strings = (typeof STRINGS)[Lang]["doctorProfile"];

  // Midday, so the date cannot slip a day in a timezone west of UTC and make the
  // assertion flaky rather than wrong.
  const EXPIRES_AT = "2030-01-31T12:00:00";

  // The expiry sentence is a function of a locale-formatted date, so the expected
  // string has to be built from the same formatting the band uses. Asserting the
  // English template in both locales would pass for the wrong reason - the
  // Hindi sentence wraps a Hindi date, and a Hindi doctor reads that pair.
  function expiryLabel(lang: Lang, s: Strings) {
    return s.credentialExpires(
      new Date(EXPIRES_AT).toLocaleDateString(
        lang === "hi" ? "hi-IN" : "en-IN",
        { day: "numeric", month: "short", year: "numeric" },
      ),
    );
  }

  // A photo, a credential with an expiry, and names - the tree in which most of
  // the band's copy is on screen at once.
  function Band({ strings }: { strings: Strings }) {
    return (
      <>
        <ProfileIdentityBand
          profile={profile({ photo_ref: "doctor/7/photo-1.enc" })}
          photoUrl={null}
          mediaAbsent={false}
          busy={false}
          failure={null}
          onPick={noop}
          onRemove={noop}
          onDismissFailure={noop}
        />
        <ProfileCredentialList
          profile={{
            credentials: [
              {
                credential_type: "medical_registration",
                status: "verified",
                expires_at: EXPIRES_AT,
              },
            ],
            partner_id: 7,
            verified: true,
          }}
        />
      </>
    );
  }

  // The two strings that render only on a fallback: the h1 with nothing left to
  // fall back to, and the empty specialty row.
  function Fallbacks({ strings }: { strings: Strings }) {
    return (
      <ProfileIdentityBand
        profile={profile({
          practice_name: null,
          clinic_name: null,
          specialties: [],
          photo_ref: null,
        })}
        photoUrl={null}
        mediaAbsent={false}
        busy={false}
        failure={null}
        onPick={noop}
        onRemove={noop}
        onDismissFailure={noop}
      />
    );
  }

  // The locale is seeded BEFORE the tree mounts, which is how the app itself
  // starts in a non-default language (LangProvider adopts the stored preference in
  // its own mount effect). Setting it from an effect instead loses the flip: a
  // child's effect runs before the provider subscribes, so the notification goes
  // nowhere and the tree stays in English - a failure that would have made these
  // tests assert Hindi strings against English markup and pass for the wrong
  // reason.
  function InLang({ lang, children }: { lang: Lang; children: ReactNode }) {
    return (
      <LangProvider>
        <LangSeed lang={lang} />
        {children}
      </LangProvider>
    );
  }

  function LangSeed({ lang }: { lang: Lang }) {
    // Rendered before the surfaces below it in the same tree, so its effect -
    // which runs first - lands the preference before any of them read it.
    useEffect(() => {
      window.localStorage.setItem("caresetu.lang", lang);
    }, [lang]);
    return null;
  }

  for (const lang of ["en", "hi"] as const) {
    describe(lang, () => {
      const s = STRINGS[lang].doctorProfile;

      it("renders the band's visible copy", () => {
        render(
          <InLang lang={lang}>
            <Band strings={s} />
          </InLang>,
        );

        for (const [name, value] of [
          ["photo help", s.photoHelp],
          ["replace action", s.photoReplace],
          ["remove action", s.photoRemove],
          ["verified badge", s.verified],
          ["credentials heading", s.credentialsHeading],
          ["credential type", s.credentialType.medical_registration],
          ["credential status", s.credentialStatus.verified],
          ["credential expiry", expiryLabel(lang, s)],
          ["public preview heading", s.publicPreviewHeading],
          ["public preview help", s.publicPreviewHelp],
          ["public preview action", s.publicPreviewAction],
          ["verified tick label", s.verifiedTickLabel],
        ] as const) {
          expect(
            screen.getAllByText(value).length,
            `${name} (${lang}) never rendered`,
          ).toBeGreaterThan(0);
        }
      });

      // These three are accessible NAMES rather than text: the picker is labelled
      // but not captioned, and the chips row is named by its label rather than by
      // a visible heading. `getByText` would not find them, which is why the
      // identity band's own name was unasserted in both locales until now.
      it("renders the band's accessible names", () => {
        render(
          <InLang lang={lang}>
            <Band strings={s} />
          </InLang>,
        );

        expect(screen.getByTestId("profile-photo")).toHaveAccessibleName(
          s.photoHeading,
        );
        expect(screen.getByTestId("profile-photo-input")).toHaveAccessibleName(
          s.photoReplace,
        );
        expect(screen.getByLabelText(s.identityChipsLabel)).toBeInTheDocument();
      });

      it("renders the verification row and its unverified wording", () => {
        render(
          <InLang lang={lang}>
            <Band strings={s} />
          </InLang>,
        );

        expect(
          screen.getByTestId("profile-verification-state"),
        ).toHaveTextContent(s.verificationStateLabel);

        cleanup();
        render(
          <ProfileIdentityBand
            profile={profile({ verified: false })}
            photoUrl={null}
            mediaAbsent={false}
            busy={false}
            failure={null}
            onPick={noop}
            onRemove={noop}
            onDismissFailure={noop}
          />,
        );
        expect(
          screen.getByTestId("profile-identity-verified"),
        ).toHaveTextContent(s.notVerified);
      });

      it("renders the band's fallback copy when there is nothing to show", () => {
        render(
          <InLang lang={lang}>
            <Fallbacks strings={s} />
          </InLang>,
        );

        expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
          s.title,
        );
        expect(
          screen.getByTestId("profile-specialties-empty"),
        ).toHaveTextContent(s.noSpecialtiesYet);
        // No photo stored, so the band offers Upload - the string the replace
        // action above deliberately was not.
        expect(screen.getByTestId("profile-photo-upload")).toHaveTextContent(
          s.photoUpload,
        );
      });

      it("names the credential list's empty state rather than a bare list", () => {
        render(
          <InLang lang={lang}>
            <ProfileCredentialList
              profile={{ credentials: [], partner_id: 7, verified: false }}
            />
          </InLang>,
        );

        expect(
          screen.getByTestId("profile-credentials-empty"),
        ).toHaveTextContent(s.credentialsEmpty);
      });
    });
  }

  // The falsifiability check: the band's OWN copy must actually differ between
  // locales. Deliberately scoped to these strings - shared vocabulary (the 20
  // specialty names, `Save`, `Cancel`) is intentionally identical in places, and
  // demanding a difference there would assert a translation the glossary does not
  // promise. A single untranslated string fails here by name.
  it("gives no band string the same text in both locales", () => {
    const en = STRINGS.en.doctorProfile;
    const hi = STRINGS.hi.doctorProfile;

    const fields: (keyof typeof en & keyof typeof hi)[] = [
      "photoHeading",
      "photoHelp",
      "photoUpload",
      "photoReplace",
      "photoRemove",
      "identityChipsLabel",
      "noSpecialtiesYet",
      "title",
      "verificationStateLabel",
      "verifiedTickLabel",
      "credentialsHeading",
      "credentialsEmpty",
      "publicPreviewHeading",
      "publicPreviewHelp",
      "publicPreviewAction",
      "verifiedBandTitle",
    ];

    const untranslated = fields.filter(
      (field) => String(en[field]) === String(hi[field]),
    );

    expect(
      untranslated,
      "these band strings are byte-identical in hi and en, so REQ-006's equal-quality copy is not met",
    ).toEqual([]);
  });
});

describe("ProfileSectionIndex", () => {
  const anchors = [
    { id: PROFILE_ANCHORS.verified, label: t.verifiedBandTitle },
    { id: PROFILE_ANCHORS.practice, label: t.practiceSectionTitle },
  ];

  it("renders plain in-page hash links and nothing that holds state", () => {
    render(<ProfileSectionIndex anchors={anchors} />);

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(2);
    expect(links[0].getAttribute("href")).toBe(`#${PROFILE_ANCHORS.verified}`);
    // "Holds no state" read as a prohibition: no button to collapse a section, no
    // aria-pressed marking an "active" section a scroll-spy would have to track,
    // and no handler of any kind on the row.
    expect(screen.queryByRole("button")).toBeNull();
    expect(document.querySelector("[aria-pressed]")).toBeNull();
    expect(document.querySelector("[aria-current]")).toBeNull();
  });

  it("names the region it is, so it is not just a row of links to a screen reader", () => {
    render(<ProfileSectionIndex anchors={anchors} />);

    expect(
      screen.getByRole("navigation", { name: t.sectionIndexLabel }),
    ).toBeInTheDocument();
  });

  it("puts the focus ring and the touch target on the anchor", () => {
    render(<ProfileSectionIndex anchors={anchors} />);

    for (const link of screen.getAllByRole("link")) {
      // The ring has to be on the `<a>`: `Badge` renders a `<div>` and its
      // `focus-visible:` classes can never match, so a ring declared there is
      // inert - and an inert ring is exactly what this assertion exists to stop
      // passing for. Asserted on the focused element, not on a descendant.
      expect(link.className).toContain("focus-visible:ring-1");
      expect(link.className).toContain("focus-visible:outline-none");
      // The ring colour is a token, not a hex (§9.4 names accent.border).
      expect(link.className).toContain("ring-accent-border");
      // `min-h-11` is 44px, and it is on the link rather than the pill: a chip
      // the reader can see but cannot comfortably tap fails the same floor a
      // missing ring does.
      expect(link.className).toContain("min-h-11");
    }
    expect(screen.getByRole("navigation").className).toContain("sticky");
  });
});
