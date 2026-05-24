import clsx from "clsx";
import type { HealthResponse } from "@/api/metrics";

interface IntegrationsHealthSummaryProps {
  health: HealthResponse | null;
}

type StatusVariant = "ok" | "error" | "unknown";

function StatusPill({ name, status }: { name: string; status: string }) {
  const variant: StatusVariant =
    status === "ok" ? "ok" : status === "error" ? "error" : "unknown";

  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        variant === "ok" && "bg-[#22c55e]/15 text-[#22c55e]",
        variant === "error" && "bg-bad/15 text-bad",
        variant === "unknown" && "bg-fg-muted/15 text-fg-muted",
      )}
    >
      <span
        className={clsx(
          "size-1.5 rounded-full",
          variant === "ok" && "bg-[#22c55e]",
          variant === "error" && "bg-bad",
          variant === "unknown" && "bg-fg-muted",
        )}
      />
      {name}
    </span>
  );
}

export function IntegrationsHealthSummary({ health }: IntegrationsHealthSummaryProps) {
  if (!health) {
    return <p className="text-xs text-fg-muted">Loading health…</p>;
  }

  return (
    <div className="flex flex-wrap gap-1.5">
      <StatusPill name="wabot daemon" status={health.wabot_daemon.status} />
      {health.mcp_servers.map((srv) => (
        <StatusPill key={srv.id} name={srv.name} status={srv.status} />
      ))}
      <StatusPill name="composio" status={health.composio.status} />
    </div>
  );
}
