import { useEffect, useState } from "react";
import { listTools, type ToolRow, type ToolKind } from "@/api/tools";
import { setAgentTools, type AgentDetail } from "@/api/agents";

const KIND_LABELS: Record<ToolKind, string> = {
  native: "Native",
  mcp: "MCP",
  composio: "Composio",
  skill_action: "Skill actions",
};

interface Props {
  agent: AgentDetail;
  onSaved: (updated: AgentDetail) => void;
  onClose: () => void;
}

export function ToolAssignmentDrawer({ agent, onSaved, onClose }: Props) {
  const [allTools, setAllTools] = useState<ToolRow[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set(agent.tool_ids));
  const [search, setSearch] = useState("");
  const [state, setState] = useState<"loading" | "ready" | "saving" | "error">("loading");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listTools()
      .then((res) => {
        setAllTools([...res.native, ...res.mcp, ...res.composio, ...res.skill_action]);
        setState("ready");
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Could not load tools");
        setState("error");
      });
  }, []);

  const q = search.toLowerCase();
  const filtered = allTools.filter(
    (t) =>
      t.name.toLowerCase().includes(q) ||
      (t.description ?? "").toLowerCase().includes(q),
  );

  const grouped = (["native", "mcp", "composio", "skill_action"] as ToolKind[]).reduce<
    Record<ToolKind, ToolRow[]>
  >(
    (acc, k) => {
      acc[k] = filtered.filter((t) => t.kind === k);
      return acc;
    },
    { native: [], mcp: [], composio: [], skill_action: [] },
  );

  function toggle(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function save() {
    setState("saving");
    setError(null);
    try {
      const updated = await setAgentTools(agent.slug, Array.from(selected));
      onSaved(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
      setState("ready");
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium">Assign tools — {agent.slug}</p>
        <button
          type="button"
          onClick={onClose}
          className="text-xs text-fg-muted hover:text-fg"
        >
          Cancel
        </button>
      </div>

      <input
        type="search"
        placeholder="Search tools…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="w-full rounded-card border border-border bg-bg-app px-3 py-2 text-xs"
      />

      {state === "loading" && <p className="text-xs text-fg-muted">Loading tools…</p>}
      {state === "error" && <p className="text-xs text-bad">{error}</p>}

      {state !== "loading" && (
        <div className="space-y-3 max-h-80 overflow-y-auto">
          {(["native", "mcp", "composio", "skill_action"] as ToolKind[]).map((kind) => {
            const rows = grouped[kind];
            if (rows.length === 0) return null;
            return (
              <div key={kind} className="space-y-1">
                <p className="text-[10px] font-medium uppercase tracking-wider text-fg-muted">
                  {KIND_LABELS[kind]} ({rows.length})
                </p>
                {rows.map((t) => (
                  <label
                    key={t.id}
                    className="flex items-start gap-2 cursor-pointer rounded-card border border-border px-3 py-2 hover:bg-bg-app"
                  >
                    <input
                      type="checkbox"
                      className="mt-0.5 flex-shrink-0"
                      checked={selected.has(t.id)}
                      onChange={() => toggle(t.id)}
                    />
                    <span className="flex flex-col gap-0.5">
                      <span className="text-xs font-medium">{t.name}</span>
                      {t.description && (
                        <span className="text-[10px] text-fg-muted line-clamp-1">
                          {t.description}
                        </span>
                      )}
                    </span>
                  </label>
                ))}
              </div>
            );
          })}
        </div>
      )}

      {error && state === "ready" && (
        <p className="text-xs text-bad">{error}</p>
      )}

      <div className="flex gap-2">
        <button
          type="button"
          disabled={state === "saving" || state === "loading"}
          onClick={() => void save()}
          className="rounded-pill bg-accent px-3 py-1.5 text-xs font-medium text-accent-fg disabled:opacity-50"
        >
          {state === "saving" ? "Saving…" : `Save (${selected.size} selected)`}
        </button>
        <button
          type="button"
          onClick={onClose}
          className="rounded-pill border border-border px-3 py-1.5 text-xs"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
