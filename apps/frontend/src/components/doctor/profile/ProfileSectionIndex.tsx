"use client";

// #615 AC 4: the sticky anchor-chip index. It is a row of in-page hash links and
// nothing else.
//
// Read the acceptance criterion as a prohibition. "Holds no state" plus "no
// section is hidden" plus "every per-section save button stays beside its own
// fields" together rule out three tempting designs:
//
// - a scroll-spy that tracks the active section and marks it (that is state, and
//   it is a different design with its own accessibility questions: an `aria-current`
//   that lies about where the reader is looking);
// - collapse/expand, which would make the index a control over what is on screen;
// - one page-level save in the index bar, which would take each save away from
//   the fields it saves.
//
// So: static chips, sticky, no observer, no handler, no state. The chip labels
// are the target sections' own headings, read from the dictionary in both locales,
// so a chip can never name a section the way the section names itself.

import { Badge } from "@/components/ui/badge";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

/**
 * The anchor vocabulary, declared here because naming the targets is this
 * component's job: the sections hang their ids on it and the page builds its chip
 * list from the same object, so a chip can never point at an id nothing renders.
 *
 * The `profile-section-` prefix is load-bearing twice over - the anchor chips
 * address these ids, and the app stylesheet scopes a scroll margin to that prefix
 * so a jumped-to heading does not land under the sticky chrome and this index.
 */
export const PROFILE_ANCHORS = {
  verified: "profile-section-verified",
  declared: "profile-section-declared",
  practice: "profile-section-practice",
  address: "profile-section-address",
  about: "profile-section-about",
  notifications: "profile-section-notifications",
  fee: "profile-section-fee",
} as const;

/** One chip: the in-page anchor it jumps to, and the label it jumps with. */
export interface ProfileSectionAnchor {
  id: string;
  label: string;
}

export function ProfileSectionIndex({
  anchors,
}: {
  anchors: ProfileSectionAnchor[];
}) {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorProfile;

  return (
    // Sticky under the console chrome's own sticky header, and above the content
    // it moves over. `scroll-mt` on each target is what keeps a jumped-to heading
    // from landing under that chrome - without it the index hides the heading the
    // reader just asked to see, which is the one thing a jump index must not do.
    <nav
      aria-label={t.sectionIndexLabel}
      data-testid="profile-section-index"
      className="sticky top-14 z-30 -mx-4 border-b border-hairline bg-surface/95 px-4 py-2 backdrop-blur"
    >
      <ul className="flex flex-wrap items-center gap-2">
        {anchors.map((anchor) => (
          <li key={anchor.id}>
            {/* The focus ring and the touch target both go on the ANCHOR, because
                the anchor is the focusable element - `Badge` renders a `<div>`, so
                its own `focus-visible:` classes can never match, and a ring
                declared there is inert. `min-h-11` is 44px on the anchor so the
                tap target is the link rather than the little pill inside it; the
                badge is then padded to fill it, so what the reader taps and what
                they see are the same size (§9.4). */}
            <a
              href={`#${anchor.id}`}
              className="inline-flex min-h-11 items-center rounded-full focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent-border"
            >
              {/* `rounded-full` because the pill is this app's chip idiom (see
                  `badge.tsx`). The badge carries the label and the colours; the
                  anchor carries the behaviour, the focus and the touch floor. */}
              <Badge
                variant="outline"
                className="border-hairline py-2.5 text-txt hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong"
                data-testid={`profile-anchor-${anchor.id}`}
              >
                {anchor.label}
              </Badge>
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
