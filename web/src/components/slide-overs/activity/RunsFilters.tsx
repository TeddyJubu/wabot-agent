interface RunsFiltersProps {
  agents: string[];
  agentFilter: string;
  windowFilter: "1h" | "24h" | "7d";
  statusFilter: "all" | "errored";
  onAgentChange: (v: string) => void;
  onWindowChange: (v: "1h" | "24h" | "7d") => void;
  onStatusChange: (v: "all" | "errored") => void;
}

export function RunsFilters({
  agents,
  agentFilter,
  windowFilter,
  statusFilter,
  onAgentChange,
  onWindowChange,
  onStatusChange,
}: RunsFiltersProps) {
  const selectClass =
    "rounded border border-border bg-bg-app px-2 py-1 text-xs text-fg focus:outline-none focus:ring-1 focus:ring-accent/40";

  return (
    <div className="flex flex-wrap gap-2 pb-3">
      <select
        value={agentFilter}
        onChange={(e) => onAgentChange(e.target.value)}
        aria-label="Filter by agent"
        className={selectClass}
      >
        <option value="">All agents</option>
        {agents.map((a) => (
          <option key={a} value={a}>
            {a}
          </option>
        ))}
      </select>

      <select
        value={windowFilter}
        onChange={(e) => onWindowChange(e.target.value as "1h" | "24h" | "7d")}
        aria-label="Filter by time window"
        className={selectClass}
      >
        <option value="1h">Last 1h</option>
        <option value="24h">Last 24h</option>
        <option value="7d">Last 7d</option>
      </select>

      <select
        value={statusFilter}
        onChange={(e) => onStatusChange(e.target.value as "all" | "errored")}
        aria-label="Filter by status"
        className={selectClass}
      >
        <option value="all">All statuses</option>
        <option value="errored">Errored only</option>
      </select>
    </div>
  );
}
