import type { Config } from "tailwindcss";
import tailwindcssAnimate from "tailwindcss-animate";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // Palette hexes live only in src/app/tokens.css (#193); this config
      // consumes the CSS variables so there is a single token source.
      colors: {
        accent: {
          DEFAULT: "var(--accent)",
          strong: "var(--accent-strong)",
          soft: "var(--accent-soft)",
          border: "var(--accent-border)",
        },
        warm: {
          DEFAULT: "var(--warm)",
          mid: "var(--warm-mid)",
          soft: "var(--warm-soft)",
        },
        success: {
          DEFAULT: "var(--success)",
          soft: "var(--success-soft)",
          text: "var(--success-text)",
        },
        warn: {
          soft: "var(--warn-soft)",
          text: "var(--warn-text)",
        },
        danger: {
          DEFAULT: "var(--danger)",
          soft: "var(--danger-soft)",
          border: "var(--danger-border)",
        },
        page: {
          bg: "var(--page-bg)",
        },
        surface: "var(--surface)",
        hairline: {
          DEFAULT: "var(--hairline)",
          soft: "var(--hairline-soft)",
        },
        "on-accent": "var(--on-accent)",
        txt: {
          DEFAULT: "var(--txt)",
          sub: "var(--txt-sub)",
          muted: "var(--txt-muted)",
        },
        scrim: "var(--scrim)",
        // shadcn/ui semantic slots (#195) - aliases over the #193 tokens.
        // The ui-* slots store H S% L% triplets (see tokens.css) so Tailwind
        // can inject alpha into the /opacity utilities the primitives use.
        background: "var(--page-bg)",
        foreground: "var(--txt)",
        popover: {
          DEFAULT: "var(--surface)",
          foreground: "var(--txt)",
        },
        primary: {
          DEFAULT: "hsl(var(--ui-primary))",
          foreground: "hsl(var(--ui-primary-fg))",
        },
        secondary: {
          DEFAULT: "hsl(var(--ui-secondary))",
          foreground: "hsl(var(--ui-secondary-fg))",
        },
        muted: {
          DEFAULT: "var(--hairline-soft)",
          foreground: "var(--txt-muted)",
        },
        destructive: {
          DEFAULT: "hsl(var(--ui-destructive))",
          foreground: "hsl(var(--ui-destructive-fg))",
        },
        border: "var(--hairline)",
        input: "var(--hairline)",
        ring: "var(--accent-border)",
      },
      borderRadius: {
        sm: "var(--radius-sm)",
        DEFAULT: "var(--radius)",
        lg: "var(--radius-lg)",
      },
      boxShadow: {
        card: "var(--shadow-card)",
        pop: "var(--shadow-pop)",
      },
    },
  },
  plugins: [tailwindcssAnimate],
};

export default config;
