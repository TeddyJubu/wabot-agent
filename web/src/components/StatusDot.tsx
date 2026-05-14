import { clsx } from "clsx";

export type StatusVariant = "ok" | "warn" | "bad" | "pending";

const TONE: Record<StatusVariant, string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  bad: "bg-bad",
  pending: "bg-fg-muted",
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
    </span>
  );
}
