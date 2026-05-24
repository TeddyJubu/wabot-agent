import { ArrowUp, ArrowDown, Minus } from "lucide-react";
import clsx from "clsx";

interface KpiCardProps {
  title: string;
  value: string;
  delta?: number | null;
  suffix?: string;
}

export function KpiCard({ title, value, delta, suffix }: KpiCardProps) {
  const hasDelta = delta !== null && delta !== undefined;
  const isUp = hasDelta && delta > 0;
  const isDown = hasDelta && delta < 0;

  return (
    <div className="flex-1 min-w-0 rounded-card border border-border bg-bg-app p-3">
      <p className="text-xs text-fg-muted truncate">{title}</p>
      <p className="mt-1 text-xl font-semibold tabular-nums truncate">
        {value}
        {suffix && <span className="text-sm font-normal text-fg-muted ml-0.5">{suffix}</span>}
      </p>
      {hasDelta ? (
        <div
          className={clsx(
            "mt-1 flex items-center gap-0.5 text-xs font-medium",
            isUp && "text-[#22c55e]",
            isDown && "text-bad",
            !isUp && !isDown && "text-fg-muted",
          )}
          aria-label={`delta ${delta}%`}
        >
          {isUp && <ArrowUp className="size-3" />}
          {isDown && <ArrowDown className="size-3" />}
          {!isUp && !isDown && <Minus className="size-3" />}
          <span>{Math.abs(delta).toFixed(0)}%</span>
        </div>
      ) : (
        <div className="mt-1 flex items-center gap-0.5 text-xs text-fg-muted" aria-label="delta nil">
          <Minus className="size-3" />
          <span>—</span>
        </div>
      )}
    </div>
  );
}
