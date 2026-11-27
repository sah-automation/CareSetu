// PHASE-2.6 T10 (#201): single source for the CareSetu brand mark. The SVG
// previously lived inline in PublicHeader (T09) and again on /staff/login;
// one component keeps the mark identical everywhere and gives future surfaces
// a place to reuse it.
//
// #961: artwork replaced with the approved bridge-cross lockup from
// prototype/phase-2-6/homepage-resolved-v2.html (medical cross above a
// bridge arc over the deck line). Strokes stay `currentColor` so existing
// consumers keep their colour context; the homepage header wraps the mark
// in the teal gradient tile that gives it the white-on-teal presentation.

interface BrandMarkProps {
  size?: number;
}

export function BrandMark({ size = 26 }: BrandMarkProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M4 24h24"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
      <path
        d="M6 24c0-7.5 4.4-12.5 10-12.5S26 16.5 26 24"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
      <path
        d="M16 3.5v6M13 6.5h6"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
      <path
        d="M10 24v-10M22 24v-10"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
    </svg>
  );
}
