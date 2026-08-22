import type { Config } from "tailwindcss";

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
  plugins: [],
};

export default config;
