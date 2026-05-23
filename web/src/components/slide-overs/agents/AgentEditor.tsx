import { useRef, useState } from "react";
import { updateAgent, deleteAgent, type AgentDetail } from "@/api/agents";
import { ToolAssignmentDrawer } from "./ToolAssignmentDrawer";
import { SkillAssignmentDrawer } from "./SkillAssignmentDrawer";
import { TestRunDrawer } from "./TestRunDrawer";
import { DeleteConfirmDialog } from "./DeleteConfirmDialog";

const HANDOFF_FILTER_OPTIONS = [
  { value: "", label: "None" },
  { value: "remove_all_tools", label: "remove_all_tools" },
];

type Drawer = "tools" | "skills" | "test" | "delete" | null;

interface Props {
  agent: AgentDetail;
  allAgentSlugs: string[];
  onBack: () => void;
  onSaved: (updated: AgentDetail) => void;
  onDeleted: (slug: string) => void;
  onDirtyChange?: (dirty: boolean) => void;
}

export function AgentEditor({ agent, allAgentSlugs, onBack, onSaved, onDeleted, onDirtyChange }: Props) {
  const [displayName, setDisplayName] = useState(agent.display_name);
  const [description, setDescription] = useState(agent.description ?? "");
  const [parentSlug, setParentSlug] = useState(agent.parent_slug ?? "");
  const [handoffFilter, setHandoffFilter] = useState(agent.handoff_filter ?? "");
  const [instructions, setInstructions] = useState(agent.instructions);
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);
  const [drawer, setDrawer] = useState<Drawer>(null);

  // Track the latest server-confirmed state (NOT the `agent` prop, which can be stale
  // if a parent re-render hasn't run yet after a tool/skill assignment save).
  const savedRef = useRef<AgentDetail>(agent);

  // Track the latest agent detail (may be updated after tool/skill assignment)
  const [localAgent, setLocalAgent] = useState<AgentDetail>(agent);

  const isDirty =
    displayName !== savedRef.current.display_name ||
    description !== (savedRef.current.description ?? "") ||
    parentSlug !== (savedRef.current.parent_slug ?? "") ||
    handoffFilter !== (savedRef.current.handoff_filter ?? "") ||
    instructions !== savedRef.current.instructions;

  function notifyDirty(dirty: boolean) {
    onDirtyChange?.(dirty);
  }

  function setDisplayNameTracked(v: string) {
    setDisplayName(v);
    notifyDirty(
      v !== savedRef.current.display_name ||
        description !== (savedRef.current.description ?? "") ||
        parentSlug !== (savedRef.current.parent_slug ?? "") ||
        handoffFilter !== (savedRef.current.handoff_filter ?? "") ||
        instructions !== savedRef.current.instructions,
    );
  }

  function setDescriptionTracked(v: string) {
    setDescription(v);
    notifyDirty(
      displayName !== savedRef.current.display_name ||
        v !== (savedRef.current.description ?? "") ||
        parentSlug !== (savedRef.current.parent_slug ?? "") ||
        handoffFilter !== (savedRef.current.handoff_filter ?? "") ||
        instructions !== savedRef.current.instructions,
    );
  }

  function setParentSlugTracked(v: string) {
    setParentSlug(v);
    notifyDirty(
      displayName !== savedRef.current.display_name ||
        description !== (savedRef.current.description ?? "") ||
        v !== (savedRef.current.parent_slug ?? "") ||
        handoffFilter !== (savedRef.current.handoff_filter ?? "") ||
        instructions !== savedRef.current.instructions,
    );
  }

  function setHandoffFilterTracked(v: string) {
    setHandoffFilter(v);
    notifyDirty(
      displayName !== savedRef.current.display_name ||
        description !== (savedRef.current.description ?? "") ||
        parentSlug !== (savedRef.current.parent_slug ?? "") ||
        v !== (savedRef.current.handoff_filter ?? "") ||
        instructions !== savedRef.current.instructions,
    );
  }

  function setInstructionsTracked(v: string) {
    setInstructions(v);
    notifyDirty(
      displayName !== savedRef.current.display_name ||
        description !== (savedRef.current.description ?? "") ||
        parentSlug !== (savedRef.current.parent_slug ?? "") ||
        handoffFilter !== (savedRef.current.handoff_filter ?? "") ||
        v !== savedRef.current.instructions,
    );
  }

  function cancel() {
    const s = savedRef.current;
    setDisplayName(s.display_name);
    setDescription(s.description ?? "");
    setParentSlug(s.parent_slug ?? "");
    setHandoffFilter(s.handoff_filter ?? "");
    setInstructions(s.instructions);
    setStatus("");
    onDirtyChange?.(false);
  }

  async function save() {
    setSaving(true);
    setStatus("Saving…");
    try {
      const updated = await updateAgent(agent.slug, {
        display_name: displayName,
        description: description || null,
        parent_slug: parentSlug || null,
        handoff_filter: handoffFilter || null,
        instructions,
      });
      savedRef.current = updated;
      setLocalAgent(updated);
      onSaved(updated);
      setStatus("Saved.");
      onDirtyChange?.(false);
    } catch (err) {
      setStatus(`Error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSaving(false);
    }
  }

  async function doDelete() {
    setSaving(true);
    try {
      await deleteAgent(agent.slug);
      onDeleted(agent.slug);
    } catch (err) {
      setStatus(`Delete failed: ${err instanceof Error ? err.message : String(err)}`);
      setSaving(false);
      setDrawer(null);
    }
  }

  const parentChoices = allAgentSlugs.filter((s) => s !== agent.slug);

  if (drawer === "tools") {
    return (
      <ToolAssignmentDrawer
        agent={localAgent}
        onSaved={(updated) => {
          savedRef.current = updated;
          setLocalAgent(updated);
          onSaved(updated);
          setDrawer(null);
        }}
        onClose={() => setDrawer(null)}
      />
    );
  }

  if (drawer === "skills") {
    return (
      <SkillAssignmentDrawer
        agent={localAgent}
        onClose={() => setDrawer(null)}
      />
    );
  }

  if (drawer === "test") {
    return (
      <TestRunDrawer slug={agent.slug} onClose={() => setDrawer(null)} />
    );
  }

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onBack}
          className="text-xs text-accent hover:underline"
        >
          ← Back
        </button>
        <span className="text-xs text-fg-muted">/</span>
        <span className="text-xs font-medium">{agent.slug}</span>
        {agent.is_builtin && (
          <span className="rounded border border-border px-1 text-[10px] text-fg-muted">
            builtin
          </span>
        )}
      </div>

      {/* Form */}
      <div className="space-y-2">
        <div className="space-y-1">
          <label className="text-[10px] font-medium uppercase tracking-wider text-fg-muted">
            Display name
          </label>
          <input
            type="text"
            value={displayName}
            onChange={(e) => setDisplayNameTracked(e.target.value)}
            className="w-full rounded-card border border-border bg-bg-app px-3 py-2 text-xs"
          />
        </div>

        <div className="space-y-1">
          <label className="text-[10px] font-medium uppercase tracking-wider text-fg-muted">
            Description
          </label>
          <input
            type="text"
            value={description}
            onChange={(e) => setDescriptionTracked(e.target.value)}
            placeholder="Optional"
            className="w-full rounded-card border border-border bg-bg-app px-3 py-2 text-xs"
          />
        </div>

        <div className="space-y-1">
          <label className="text-[10px] font-medium uppercase tracking-wider text-fg-muted">
            Parent agent
          </label>
          <select
            value={parentSlug}
            onChange={(e) => setParentSlugTracked(e.target.value)}
            className="w-full rounded-card border border-border bg-bg-app px-3 py-2 text-xs"
          >
            <option value="">— none (root) —</option>
            {parentChoices.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>

        <div className="space-y-1">
          <label className="text-[10px] font-medium uppercase tracking-wider text-fg-muted">
            Handoff filter
          </label>
          <select
            value={handoffFilter}
            onChange={(e) => setHandoffFilterTracked(e.target.value)}
            className="w-full rounded-card border border-border bg-bg-app px-3 py-2 text-xs"
          >
            {HANDOFF_FILTER_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>

        <div className="space-y-1">
          <label className="text-[10px] font-medium uppercase tracking-wider text-fg-muted">
            Instructions
          </label>
          <textarea
            rows={8}
            value={instructions}
            onChange={(e) => setInstructionsTracked(e.target.value)}
            className="w-full rounded-card border border-border bg-bg-app px-3 py-2 text-xs font-mono resize-y"
          />
        </div>
      </div>

      {/* Tool / Skill summary */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between text-xs">
          <span className="text-fg-muted">
            Tools assigned ({localAgent.tool_ids.length})
          </span>
          <button
            type="button"
            onClick={() => setDrawer("tools")}
            className="text-accent hover:underline"
          >
            Manage…
          </button>
        </div>
        <div className="flex items-center justify-between text-xs">
          <span className="text-fg-muted">
            Skills assigned ({localAgent.skill_ids.length})
          </span>
          <button
            type="button"
            onClick={() => setDrawer("skills")}
            className="text-accent hover:underline"
          >
            Manage…
          </button>
        </div>
      </div>

      {/* Test run */}
      <button
        type="button"
        onClick={() => setDrawer("test")}
        className="w-full rounded-card border border-border px-3 py-2 text-xs text-fg-muted hover:bg-bg-app"
      >
        ▶ Test run
      </button>

      {/* Delete confirmation inline */}
      {drawer === "delete" && (
        <DeleteConfirmDialog
          agentSlug={agent.slug}
          onConfirm={() => void doDelete()}
          onCancel={() => setDrawer(null)}
          busy={saving}
        />
      )}

      {/* Action bar */}
      <div className="flex items-center justify-between gap-2 border-t border-border pt-3">
        <div className="flex gap-2">
          <button
            type="button"
            disabled={saving || !isDirty}
            onClick={() => void save()}
            className="rounded-pill bg-accent px-3 py-1.5 text-xs font-medium text-accent-fg disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save"}
          </button>
          <button
            type="button"
            disabled={saving || !isDirty}
            onClick={cancel}
            className="rounded-pill border border-border px-3 py-1.5 text-xs disabled:opacity-40"
          >
            Cancel
          </button>
        </div>
        <button
          type="button"
          disabled={agent.is_builtin || saving}
          title={agent.is_builtin ? "Built-in agents cannot be deleted" : "Delete agent"}
          onClick={() => setDrawer("delete")}
          className="rounded-pill border border-bad/40 px-3 py-1.5 text-xs text-bad hover:bg-bad/10 disabled:cursor-not-allowed disabled:opacity-30"
        >
          Delete
        </button>
      </div>

      {status && (
        <p className="text-xs text-fg-muted">{status}</p>
      )}
    </div>
  );
}
