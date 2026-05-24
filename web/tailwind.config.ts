import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // <alpha-value> placeholders let Tailwind's opacity modifiers
        // (`bg-ok/10`, `text-bad/90`, `border-warn/40`, …) compose against
        // every semantic token. Phase D · L5 leans on this so destructive /
        // status surfaces can drop ad-hoc red/green/yellow utilities for the
        // semantic ones.
        bg: {
          app: "hsl(var(--bg-app) / <alpha-value>)",
          card: "hsl(var(--bg-card) / <alpha-value>)",
        },
        fg: {
          DEFAULT: "hsl(var(--fg-default) / <alpha-value>)",
          muted: "hsl(var(--fg-muted) / <alpha-value>)",
        },
        border: "hsl(var(--border) / <alpha-value>)",
        accent: {
          DEFAULT: "hsl(var(--accent) / <alpha-value>)",
          fg: "hsl(var(--accent-fg) / <alpha-value>)",
        },
        ok: "hsl(var(--ok) / <alpha-value>)",
        warn: "hsl(var(--warn) / <alpha-value>)",
        bad: "hsl(var(--bad) / <alpha-value>)",
      },
      fontFamily: {
        sans: ["Geist Sans", "Inter", "system-ui", "sans-serif"],
        mono: ["Geist Mono", "ui-monospace", "monospace"],
      },
      borderRadius: { card: "16px", pill: "999px" },
      boxShadow: { sm: "0 1px 2px rgba(15,17,21,0.04)" },
      transitionTimingFunction: { out: "cubic-bezier(0.22, 1, 0.36, 1)" },
    },
  },
  plugins: [],
} satisfies Config;
