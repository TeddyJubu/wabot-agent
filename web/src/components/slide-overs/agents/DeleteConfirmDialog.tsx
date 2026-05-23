interface Props {
  agentSlug: string;
  onConfirm: () => void;
  onCancel: () => void;
  busy: boolean;
}

export function DeleteConfirmDialog({ agentSlug, onConfirm, onCancel, busy }: Props) {
  return (
    <div className="rounded-card border border-bad/40 bg-bad/10 p-3 space-y-2 text-xs">
      <p className="font-medium text-bad">Delete agent &ldquo;{agentSlug}&rdquo;?</p>
      <p className="text-fg-muted">This cannot be undone. Tool assignments will be removed.</p>
      <div className="flex gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={onConfirm}
          className="rounded-pill bg-bad px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
        >
          {busy ? "Deleting…" : "Delete"}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={onCancel}
          className="rounded-pill border border-border px-3 py-1 text-xs"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
