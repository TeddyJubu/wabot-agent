import { clsx } from "clsx";
import type { ReactNode } from "react";

export type StatusVariant = "ok" | "warn" | "bad" | "pending";

const TONE: Record<StatusVariant, string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  bad: "bg-bad",
  pending: "bg-fg-muted",
};

// Inner glyphs reinforce the colour-coded variant so the dot conveys state
// through *icon and colour* — never colour alone (WCAG 1.4.1).  Each glyph is
// drawn in an 8×8 viewBox using `currentColor` so it picks up the contrasting
// `text-bg-app` token applied on the wrapping <svg>.
const GLYPH: Record<StatusVariant, ReactNode> = {
  // check mark ✓
  ok: <path d="M1.75 4.25 L3.25 5.75 L6.25 2.5" />,
  // exclamation mark !
  warn: (
    <>
      <path d="M4 1.75 L4 4.75" />
      <path d="M4 6.25 L4 6.5" />
    </>
  ),
  // cross ✕
  bad: (
    <>
      <path d="M2 2 L6 6" />
      <path d="M6 2 L2 6" />
    </>
  ),
  // ellipsis · · ·
  pending: (
    <>
      <path d="M2 4 L2 4" />
      <path d="M4 4 L4 4" />
      <path d="M6 4 L6 4" />
    </>
  ),
};

interface Props {
  variant: StatusVariant;
  className?: string;
  animated?: boolean;
}

export default function StatusDot({ variant, className, animated = true }: Props) {
  return (
    <span
      aria-hidden
      className={clsx("relative inline-flex size-2 items-center justify-center", className)}
    >
      <span
        className={clsx(
          "absolute inline-flex size-2 rounded-full",
          TONE[variant],
          animated && variant === "ok" && "shimmer",
        )}
      />
      <svg
        aria-hidden
        viewBox="0 0 8 8"
        className="absolute size-2 text-bg-app"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {GLYPH[variant]}
      </svg>
    </span>
  );
}
