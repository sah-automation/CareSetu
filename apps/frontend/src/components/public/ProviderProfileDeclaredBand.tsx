// #619: the DECLARED band of the public provider profile (FEAT-005, MOD-002).
//
// The other half of `ProviderProfileBody`, split out because it is the half with
// its own rules. It renders what the provider SAYS about itself - the clinic they
// practise in, every specialty they offer, the languages they are understood in,
// when they consult, where they are, how long they have done this and what they
// say about it - and every one of those is a claim nobody checked.
//
// Which is why the band looks the way it does. Its edge is DASHED where every
// verified band is solid, so the boundary reads before any copy is read; and the
// note under the heading says in words that CareSetu has not checked any of it.
// Neither does the other's job: a patient reads the shape, and nobody has to know
// what a dashed border means to know which half of the page nobody vouched for.
//
// Three rules this file will not break:
//
//   - No declared field renders a verified marker, however trustworthy it looks.
//     A declared field is not in the verified band because it reads well; it is
//     not in the verified band at all.
//   - A field the projection does not carry renders NOTHING. A null, an empty
//     selection and a blank string are all states a provider can legitimately
//     hold, and each renders as absence rather than as a blank row or an
//     invented string. Where the band would have nothing in it, the band is not
//     rendered at all - an empty heading over nothing is a section claiming
//     "we have nothing to check here" without the words to mean it.
//   - The provider's own words stay verbatim. `about` and `consulting_hours` are
//     prose the provider wrote, so they are rendered as prose and never
//     reformatted, tidied or translated.
//
// The band shares the renderer's projection: this is a presentational component
// with no transport, driven by the same `ProviderProfile` the public page fetches
// and the doctor's live preview projects, so the two surfaces cannot drift.

import { declaredText, type ProviderProfile } from "@/lib/directory/profile";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

// The label maps this band reads are `STRINGS[lang].doctorProfile`'s, not a second
// set copied in: these are the same closed lists the doctor's own editor offers, so
// a second set of Hindi words for "Wednesday" would be a second place to reword a
// day and a second place to get it wrong. `profileVocabularies.test.ts` already
// holds those maps to every member of every list, in both locales.
//
// The one thing that does NOT come from there is the landmark label, because the
// editor's copy says "optional" - an instruction to a doctor filling in a form,
// and on a patient-facing page a landmark they saved is not optional.

/** The label for one member of a closed vocabulary, or `null` when this client
 * cannot name it. `null` is the honest answer for a value the map does not hold -
 * a row can outlive the vocabulary it was written against - and dropping it keeps
 * the rule the same everywhere: no label, no value, no invented string. */
function labelFor(
  labels: Record<string, string>,
  value: string,
): string | null {
  const label = labels[value];
  return typeof label === "string" && label !== "" ? label : null;
}

/** A declared selection as one line of text: every member this client can name, in
 * the provider's own declared order, and nothing for a member it cannot. */
function declaredSelectionText(
  labels: Record<string, string>,
  selection: readonly string[],
): string | null {
  const named = selection
    .map((value) => labelFor(labels, value))
    .filter((label): label is string => label !== null);
  return named.length > 0 ? named.join(", ") : null;
}

/** The structured address, as the separately declared parts the provider saved.
 * Each part keeps its FIELD name beside its label because the field name is what
 * identifies it to a test and a screen reader, while the label is what identifies
 * it to a patient - and the label changes with the language. A part that was not
 * declared is dropped, so a half-saved address shows the half that exists rather
 * than five rows of which two are blank. */
function declaredAddressParts(
  profile: ProviderProfile,
  landmarkLabel: string,
  address: {
    addressLineLabel: string;
    addressLocalityLabel: string;
    addressCityLabel: string;
    addressPinLabel: string;
  },
): [string, string, string][] {
  return (
    [
      ["address-line", address.addressLineLabel, profile.address_line],
      ["landmark", landmarkLabel, profile.landmark],
      // `locality`, and only `locality`. The payload also carries `area`, and
      // since #612/#613 that is the SAME fact - the server serves both from
      // `address_locality` - so falling back to it would be dead code that
      // pretends a second source exists. It is here rather than in the summary
      // band because the narrow surfaces read `area` and this band reads the
      // field it names, which is why the two agree about where a practice is.
      ["locality", address.addressLocalityLabel, profile.locality],
      ["city", address.addressCityLabel, profile.city],
      ["pin-code", address.addressPinLabel, profile.pin_code],
    ] as const
  )
    .map(([field, label, value]) => [field, label, declaredText(value)])
    .filter((row): row is [string, string, string] => row[2] !== null);
}

function DeclaredRow({
  label,
  value,
  testId,
}: {
  label: string;
  value: string;
  testId?: string;
}) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-txt-muted">{label}</dt>
      <dd className="text-right font-medium text-txt" data-testid={testId}>
        {value}
      </dd>
    </div>
  );
}

function DeclaredGroup({
  testId,
  heading,
  children,
}: {
  testId: string;
  heading: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mt-4" data-testid={testId}>
      <h3 className="text-xs font-semibold uppercase tracking-wide text-txt-muted">
        {heading}
      </h3>
      <dl className="mt-1.5 space-y-2 text-sm">{children}</dl>
    </div>
  );
}

/** Everything the provider says about itself, or nothing at all. */
export function ProviderProfileDeclaredBand({
  profile,
}: {
  profile: ProviderProfile;
}) {
  const { lang } = useLang();
  const t = STRINGS[lang].providerProfile;
  const vocab = STRINGS[lang].doctorProfile;

  const declared = {
    clinicName: declaredText(profile.clinic_name),
    specialties: declaredSelectionText(
      vocab.specialtyLabels,
      profile.specialties,
    ),
    languages: declaredSelectionText(vocab.languageLabels, profile.languages),
    consultingDays: declaredSelectionText(
      vocab.dayLabels,
      profile.consulting_days,
    ),
    consultingHours: declaredText(profile.consulting_hours),
    about: declaredText(profile.about),
    // `0` is a fact a provider can declare and renders as one. A truthiness check
    // here would report a provider with no experience as having declared nothing,
    // which is a different claim and the wrong one.
    experience:
      typeof profile.experience_years === "number"
        ? t.yearsOfExperience(profile.experience_years)
        : null,
    address: declaredAddressParts(profile, t.declaredLandmarkLabel, vocab),
  };

  const declaresSomething =
    declared.clinicName !== null ||
    declared.specialties !== null ||
    declared.languages !== null ||
    declared.consultingDays !== null ||
    declared.consultingHours !== null ||
    declared.about !== null ||
    declared.experience !== null ||
    declared.address.length > 0;

  if (!declaresSomething) return null;

  return (
    <section
      className="mt-3 rounded-lg border border-dashed border-hairline bg-surface p-5 shadow-card"
      data-testid="profile-declared"
    >
      <h2 className="text-base font-semibold text-txt">{t.declaredHeading}</h2>
      <p
        className="mt-1 text-xs text-txt-muted"
        data-testid="profile-declared-note"
      >
        {t.declaredNote}
      </p>

      {declared.clinicName || declared.specialties ? (
        <DeclaredGroup
          testId="profile-declared-practice"
          heading={t.declaredPracticeHeading}
        >
          {declared.clinicName ? (
            <DeclaredRow
              label={t.clinicNameLabel}
              value={declared.clinicName}
              testId="profile-declared-clinic-name"
            />
          ) : null}
          {declared.specialties ? (
            <DeclaredRow
              label={t.specialtiesLabel}
              value={declared.specialties}
              testId="profile-declared-specialties"
            />
          ) : null}
        </DeclaredGroup>
      ) : null}

      {declared.address.length > 0 ? (
        <DeclaredGroup
          testId="profile-declared-address"
          heading={t.declaredAddressHeading}
        >
          {declared.address.map(([field, label, value]) => (
            <DeclaredRow
              key={field}
              label={label}
              value={value}
              testId={`profile-declared-address-${field}`}
            />
          ))}
        </DeclaredGroup>
      ) : null}

      {declared.languages ||
      declared.consultingDays ||
      declared.consultingHours ||
      declared.experience ? (
        <DeclaredGroup
          testId="profile-declared-consulting"
          heading={t.declaredConsultingHeading}
        >
          {declared.languages ? (
            <DeclaredRow
              label={t.languagesLabel}
              value={declared.languages}
              testId="profile-declared-languages"
            />
          ) : null}
          {declared.consultingDays ? (
            <DeclaredRow
              label={t.consultingDaysLabel}
              value={declared.consultingDays}
              testId="profile-declared-days"
            />
          ) : null}
          {declared.consultingHours ? (
            <DeclaredRow
              label={t.consultingHoursLabel}
              value={declared.consultingHours}
              testId="profile-declared-hours"
            />
          ) : null}
          {declared.experience ? (
            <DeclaredRow
              label={t.experienceLabel}
              value={declared.experience}
              testId="profile-declared-experience"
            />
          ) : null}
        </DeclaredGroup>
      ) : null}

      {/* Prose, not a label/value row: `about` is not a value, it is the one
          declared field long enough that reading it as a value would flatten it. */}
      {declared.about ? (
        <div className="mt-4" data-testid="profile-declared-about-block">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-txt-muted">
            {t.declaredAboutHeading}
          </h3>
          <p
            className="mt-1.5 text-sm text-txt-sub"
            data-testid="profile-declared-about"
          >
            {declared.about}
          </p>
        </div>
      ) : null}
    </section>
  );
}
