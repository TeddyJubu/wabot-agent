import { CheckCircle2, AlertCircle, XCircle, RefreshCw } from "lucide-react";
import type { ToolAction, WabotStatusData } from "@/types/ui-envelope";

interface Props {
  data: WabotStatusData;
  actions: ToolAction[];
  onAction: (id: string) => void;
}

const ICONS = {
  ok: CheckCircle2,
  warn: AlertCircle,
  bad: XCircle,
} as const;

const COLORS = {
  ok: "text-ok",
  warn: "text-warn",
  bad: "text-bad",
} as const;

function fmtUptime(seconds?: number): string {
  if (seconds == null || seconds < 0) return "—";
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

export default function WabotStatusCard({ data, actions, onAction }: Props) {
  const Icon = ICONS[data.status];
  return (
    <div className="rounded-card border border-border bg-bg-card p-4 shadow-sm">
      <div className="flex items-start gap-3">
        <Icon className={`mt-0.5 size-5 ${COLORS[data.status]}`} aria-hidden />
        <div className="flex-1">
          <div className="flex items-baseline justify-between gap-3">
            <h3 className="text-sm font-medium">wabot daemon</h3>
            <span className="font-mono text-xs text-fg-muted">{data.version ?? "—"}</span>
          </div>
          <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-fg-muted">
            <div>
              <dt className="inline">uptime </dt>
              <dd className="inline font-mono text-fg">{fmtUptime(data.uptime_s)}</dd>
            </div>
            <div>
              <dt className="inline">last seen </dt>
              <dd className="inline font-mono text-fg">{data.last_seen_s ?? "—"}s ago</dd>
            </div>
          </dl>
          {data.error && <p className="mt-2 text-xs text-bad">{data.error}</p>}
          {actions.length > 0 && (
            <div className="mt-3 flex gap-2">
              {actions.map((a) => (
                <button
                  key={a.id}
                  onClick={() => onAction(a.id)}
                  className="inline-flex items-center gap-1.5 rounded-pill border border-border px-2.5 py-1 text-xs hover:bg-bg-app"
                >
                  <RefreshCw className="size-3" aria-hidden /> {a.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
