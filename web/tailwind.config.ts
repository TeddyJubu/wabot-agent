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
        // New in Verdana — Info / new feature surfaces.
        info: "hsl(var(--info) / <alpha-value>)",
      },
      fontFamily: {
        // Verdana Health typography stacks. Loaded via web/index.html
        // <link>s; system fallbacks keep the UI readable before the web
        // fonts arrive.
        sans: [
          "DM Sans",
          "Inter",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "sans-serif",
        ],
        display: [
          "Plus Jakarta Sans",
          "DM Sans",
          "Inter",
          "system-ui",
          "sans-serif",
        ],
        mono: [
          "Fira Code",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "monospace",
        ],
      },
      borderRadius: {
        // Verdana Health radius scale (design.md).
        // DEFAULT drops from 16px → 8px so cards / buttons / inputs read
        // as the calmer, more clinical pill-shape the spec calls for.
        // `card` keeps the legacy 8px (was 16px) so existing className
        // call-sites continue to resolve without per-component edits.
        sm: "4px",
        DEFAULT: "8px",
        md: "12px",
        lg: "16px",
        card: "8px",
        pill: "9999px",
        full: "9999px",
      },
      boxShadow: {
        // Verdana Health elevation — gentle, diffused. All shadows use the
        // navy ink (#0F172A) at low opacity so the elevation feels clinical
        // rather than dramatic. Matches the spec one-to-one.
        sm: "0 1px 3px rgba(15, 23, 42, 0.03)",
        DEFAULT: "0 2px 6px rgba(15, 23, 42, 0.05)",
        md: "0 4px 16px rgba(15, 23, 42, 0.07)",
        lg: "0 8px 32px rgba(15, 23, 42, 0.10)",
      },
      transitionTimingFunction: { out: "cubic-bezier(0.22, 1, 0.36, 1)" },
      letterSpacing: {
        // Used on uppercase chip labels per spec ("polished, medical-grade").
        chip: "0.05em",
      },
    },
  },
  plugins: [],
} satisfies Config;
