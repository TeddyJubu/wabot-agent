import { type ReactNode } from "react";

export function Suggestion({ children, onClick }: { children: ReactNode; onClick?: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-pill border border-border bg-bg-card px-3 py-1.5 text-xs text-fg-muted transition hover:border-accent/40 hover:text-fg"
    >
      {children}
    </button>
  );
}
