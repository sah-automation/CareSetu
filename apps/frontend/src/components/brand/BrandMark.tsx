// PHASE-2.6 T10 (#201): single source for the CareSetu brand mark. The SVG
// previously lived inline in PublicHeader (T09) and again on /staff/login;
// one component keeps the mark identical everywhere and gives future surfaces
// a place to reuse it.

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
        d="M8 24v-8M24 24v-8"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <path
        d="M8 16Q16 5 24 16"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <path
        d="M4 27h24"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
    </svg>
  );
}
