import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        bg: { app: "hsl(var(--bg-app))", card: "hsl(var(--bg-card))" },
        fg: { DEFAULT: "hsl(var(--fg-default))", muted: "hsl(var(--fg-muted))" },
        border: "hsl(var(--border))",
        accent: { DEFAULT: "hsl(var(--accent))", fg: "hsl(var(--accent-fg))" },
        ok: "hsl(var(--ok))",
        warn: "hsl(var(--warn))",
        bad: "hsl(var(--bad))",
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
