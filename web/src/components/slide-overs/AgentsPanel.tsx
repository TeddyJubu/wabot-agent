import { useEffect, useState } from "react";
import { listAgents, getAgent, type AgentSummary, type AgentDetail } from "@/api/agents";
import { AgentList } from "./agents/AgentList";
import { AgentEditor } from "./agents/AgentEditor";
import { AgentCreateForm } from "./agents/AgentCreateForm";

type View = "list" | "editor" | "create";

export default function AgentsPanel() {
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [selected, setSelected] = useState<AgentDetail | null>(null);
  const [view, setView] = useState<View>("list");
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [editorDirty, setEditorDirty] = useState(false);

  useEffect(() => {
    void load();
  }, []);

  async function load() {
    setState("loading");
    setError(null);
    try {
      setAgents(await listAgents());
      setState("ready");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load agents");
      setState("error");
    }
  }

  async function openEditor(slug: string) {
    setError(null);
    try {
      const detail = await getAgent(slug);
      setSelected(detail);
      setView("editor");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load agent");
    }
  }

  function handleSaved(updated: AgentDetail) {
    setSelected(updated);
    // Refresh the summary list so tool_count/skill_count update
    setAgents((prev) =>
      prev.map((a) =>
        a.slug === updated.slug
          ? {
              ...a,
              display_name: updated.display_name,
              description: updated.description,
              is_enabled: updated.is_enabled,
              parent_slug: updated.parent_slug,
              handoff_filter: updated.handoff_filter,
              tool_count: updated.tool_ids.length,
              skill_count: updated.skill_ids.length,
              updated_at: updated.updated_at,
            }
          : a,
      ),
    );
  }

  function handleDeleted(slug: string) {
    setAgents((prev) => prev.filter((a) => a.slug !== slug));
    setSelected(null);
    setEditorDirty(false);
    setView("list");
  }

  function handleBack() {
    if (editorDirty && !window.confirm("Discard unsaved changes?")) return;
    setEditorDirty(false);
    setView("list");
    setSelected(null);
  }

  function handleCreated(agent: AgentDetail) {
    // Add to the summary list
    setAgents((prev) => [
      ...prev,
      {
        id: agent.id,
        slug: agent.slug,
        display_name: agent.display_name,
        description: agent.description,
        is_builtin: agent.is_builtin,
        is_enabled: agent.is_enabled,
        parent_slug: agent.parent_slug,
        handoff_filter: agent.handoff_filter,
        tool_count: agent.tool_ids.length,
        skill_count: agent.skill_ids.length,
        updated_at: agent.updated_at,
      },
    ]);
    setSelected(agent);
    setView("editor");
  }

  const allSlugs = agents.map((a) => a.slug);

  return (
    <div className="space-y-3">
      {/* Top action bar — only shown on list view */}
      {view === "list" && (
        <div className="flex items-center justify-between">
          <p className="text-[10px] font-medium uppercase tracking-wider text-fg-muted">
            {state === "loading" ? "Loading…" : `${agents.length} agents`}
          </p>
          <button
            type="button"
            onClick={() => setView("create")}
            className="rounded-pill border border-border px-2.5 py-1 text-xs hover:bg-bg-app"
          >
            + New
          </button>
        </div>
      )}

      {error && (
        <p className="rounded-card border border-bad/40 bg-bad/10 px-3 py-2 text-xs text-bad">
          {error}
        </p>
      )}

      {state === "loading" && (
        <p className="text-xs text-fg-muted">Loading agents…</p>
      )}

      {state === "ready" && view === "list" && (
        <AgentList agents={agents} onSelect={(s) => void openEditor(s)} />
      )}

      {state === "ready" && view === "editor" && selected && (
        <AgentEditor
          agent={selected}
          allAgentSlugs={allSlugs}
          onBack={handleBack}
          onSaved={handleSaved}
          onDeleted={handleDeleted}
          onDirtyChange={setEditorDirty}
        />
      )}

      {view === "create" && (
        <AgentCreateForm
          allAgentSlugs={allSlugs}
          onCreated={handleCreated}
          onCancel={() => setView("list")}
        />
      )}
    </div>
  );
}
