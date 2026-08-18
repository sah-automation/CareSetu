import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        accent: {
          DEFAULT: "#0e7490",
          strong: "#155e75",
          soft: "#ecfeff",
          border: "#bae6fd",
        },
        success: {
          DEFAULT: "#10b981",
          soft: "#dcfce7",
          text: "#166534",
        },
        warn: {
          soft: "#fef3c7",
          text: "#92400e",
        },
        danger: {
          DEFAULT: "#b91c1c",
          soft: "#fef2f2",
          border: "#fecaca",
        },
        page: {
          bg: "#f8fafc",
        },
        surface: "#ffffff",
        hairline: {
          DEFAULT: "#e2e8f0",
          soft: "#eef2f7",
        },
        "on-accent": "#ffffff",
        txt: {
          DEFAULT: "#0f172a",
          sub: "#334155",
          muted: "#64748b",
        },
      },
      borderRadius: {
        sm: "0.5rem",
        DEFAULT: "0.75rem",
        lg: "1rem",
      },
      boxShadow: {
        card: "0 1px 3px rgba(2, 6, 23, 0.08)",
        pop: "0 12px 32px rgba(2, 6, 23, 0.18)",
      },
    },
  },
  plugins: [],
};

export default config;
