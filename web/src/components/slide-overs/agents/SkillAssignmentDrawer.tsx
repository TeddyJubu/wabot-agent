import type { AgentDetail } from "@/api/agents";

interface Props {
  agent: AgentDetail;
  onClose: () => void;
}

/**
 * Skill assignment placeholder — Skills install lands in Phase 4.
 * The skills table is empty on Phase 3b deployments, so this shows an
 * informative empty state rather than a broken UI.
 */
export function SkillAssignmentDrawer({ agent, onClose }: Props) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium">Assign skills — {agent.slug}</p>
        <button
          type="button"
          onClick={onClose}
          className="text-xs text-fg-muted hover:text-fg"
        >
          Close
        </button>
      </div>

      <div className="rounded-card border border-border bg-bg-app p-4 text-center space-y-2">
        <p className="text-xs text-fg-muted">No skills installed yet.</p>
        <p className="text-[10px] text-fg-muted">
          Skills install lands in Phase 4. Once installed, skills will appear
          here as checkboxes you can assign per agent.
        </p>
      </div>

      <button
        type="button"
        onClick={onClose}
        className="rounded-pill border border-border px-3 py-1.5 text-xs"
      >
        Close
      </button>
    </div>
  );
}
