import { useState } from "react";
import { createAgent, type AgentDetail } from "@/api/agents";

const SLUG_RE = /^[a-z][a-z0-9_]{1,63}$/;

interface Props {
  allAgentSlugs: string[];
  onCreated: (agent: AgentDetail) => void;
  onCancel: () => void;
}

export function AgentCreateForm({ allAgentSlugs, onCreated, onCancel }: Props) {
  const [slug, setSlug] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [instructions, setInstructions] = useState("");
  const [parentSlug, setParentSlug] = useState("");
  const [status, setStatus] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const slugError =
    slug.length > 0 && !SLUG_RE.test(slug)
      ? "Slug must start with a lowercase letter, contain only a–z / 0–9 / _, and be 2–64 chars."
      : null;

  const canSubmit =
    !submitting &&
    slug.length > 0 &&
    !slugError &&
    displayName.trim().length > 0 &&
    instructions.trim().length > 0;

  async function submit() {
    if (!canSubmit) return;
    setSubmitting(true);
    setStatus("Creating…");
    try {
      const agent = await createAgent({
        slug,
        display_name: displayName.trim(),
        description: description.trim() || null,
        instructions: instructions.trim(),
        parent_slug: parentSlug || null,
      });
      onCreated(agent);
    } catch (err) {
      setStatus(`Error: ${err instanceof Error ? err.message : String(err)}`);
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium">New agent</p>
        <button
          type="button"
          onClick={onCancel}
          className="text-xs text-fg-muted hover:text-fg"
        >
          Cancel
        </button>
      </div>

      <div className="space-y-2">
        <div className="space-y-1">
          <label className="text-[10px] font-medium uppercase tracking-wider text-fg-muted">
            Slug *
          </label>
          <input
            type="text"
            value={slug}
            onChange={(e) => setSlug(e.target.value.toLowerCase())}
            placeholder="my_researcher"
            className={`w-full rounded-card border bg-bg-app px-3 py-2 text-xs font-mono ${
              slugError ? "border-bad/60" : "border-border"
            }`}
          />
          {slugError && <p className="text-[10px] text-bad">{slugError}</p>}
        </div>

        <div className="space-y-1">
          <label className="text-[10px] font-medium uppercase tracking-wider text-fg-muted">
            Display name *
          </label>
          <input
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="My Researcher"
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
            onChange={(e) => setDescription(e.target.value)}
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
            onChange={(e) => setParentSlug(e.target.value)}
            className="w-full rounded-card border border-border bg-bg-app px-3 py-2 text-xs"
          >
            <option value="">— none (root) —</option>
            {allAgentSlugs.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>

        <div className="space-y-1">
          <label className="text-[10px] font-medium uppercase tracking-wider text-fg-muted">
            Instructions *
          </label>
          <textarea
            rows={6}
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            placeholder="You are the …"
            className="w-full rounded-card border border-border bg-bg-app px-3 py-2 text-xs font-mono resize-y"
          />
        </div>
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={!canSubmit}
          onClick={() => void submit()}
          className="rounded-pill bg-accent px-3 py-1.5 text-xs font-medium text-accent-fg disabled:opacity-50"
        >
          {submitting ? "Creating…" : "Create"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-pill border border-border px-3 py-1.5 text-xs"
        >
          Cancel
        </button>
        {status && <span className="text-xs text-fg-muted">{status}</span>}
      </div>
    </div>
  );
}
