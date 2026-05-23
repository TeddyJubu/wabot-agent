import type { AgentSummary } from "@/api/agents";

interface Props {
  agents: AgentSummary[];
  onSelect: (slug: string) => void;
}

function AgentRow({ agent, onSelect }: { agent: AgentSummary; onSelect: (s: string) => void }) {
  return (
    <button
      type="button"
      onClick={() => onSelect(agent.slug)}
      className="flex w-full items-start justify-between gap-3 rounded-card border border-border px-3 py-2 text-left text-xs transition hover:bg-bg-app"
    >
      <span className="flex flex-col gap-0.5">
        <span className="flex items-center gap-1.5 font-medium text-sm">
          <span
            className={`inline-block size-1.5 rounded-full flex-shrink-0 ${
              agent.is_enabled ? "bg-green-400" : "bg-fg-muted"
            }`}
          />
          {agent.slug}
        </span>
        {agent.display_name !== agent.slug && (
          <span className="text-fg-muted">{agent.display_name}</span>
        )}
      </span>
      <span className="flex flex-col items-end gap-0.5 text-fg-muted flex-shrink-0">
        {agent.tool_count > 0 && <span>{agent.tool_count} tools</span>}
        {agent.handoff_filter && (
          <span className="rounded border border-border px-1 text-[10px]">filter</span>
        )}
      </span>
    </button>
  );
}

export function AgentList({ agents, onSelect }: Props) {
  const builtins = agents.filter((a) => a.is_builtin);
  const customs = agents.filter((a) => !a.is_builtin);

  return (
    <div className="space-y-4">
      <section className="space-y-1.5">
        <p className="text-[10px] font-medium uppercase tracking-wider text-fg-muted">
          Builtins ({builtins.length})
        </p>
        {builtins.length === 0 ? (
          <p className="text-xs text-fg-muted">No builtin agents found.</p>
        ) : (
          builtins.map((a) => <AgentRow key={a.slug} agent={a} onSelect={onSelect} />)
        )}
      </section>
      <section className="space-y-1.5">
        <p className="text-[10px] font-medium uppercase tracking-wider text-fg-muted">
          Custom ({customs.length})
        </p>
        {customs.length === 0 ? (
          <p className="text-xs text-fg-muted">(empty — create one with + New)</p>
        ) : (
          customs.map((a) => <AgentRow key={a.slug} agent={a} onSelect={onSelect} />)
        )}
      </section>
    </div>
  );
}
