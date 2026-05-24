import { useState } from "react";
import {
  refreshComposioConnection,
  deleteComposioConnection,
} from "@/api/composio";
import type {
  ComposioConnection,
  ComposioConnectionStatus,
} from "@/api/composio";
import { ConfirmDialog } from "@/components/ConfirmDialog";

interface Props {
  connection: ComposioConnection;
  onRefreshed: (updated: ComposioConnection) => void;
  onDeleted: (id: number) => void;
}

function relativeTime(iso: string | null): string {
  if (!iso) return "never";
  const diffMs = Date.now() - new Date(iso).getTime();
  const s = Math.floor(diffMs / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function StatusPill({ status }: { status: ComposioConnectionStatus }) {
  const variants: Record<ComposioConnectionStatus, string> = {
    connected: "border-ok/40 bg-ok/10 text-ok",
    pending: "border-warn/40 bg-warn/10 text-warn",
    error: "border-bad/40 bg-bad/10 text-bad",
    disconnected: "border-border bg-transparent text-fg-muted",
  };
  return (
    <span className={`inline-block rounded border px-1.5 py-0.5 text-[9px] font-medium ${variants[status]}`}>
      {status}
    </span>
  );
}

export function ComposioConnectionRow({ connection, onRefreshed, onDeleted }: Props) {
  const [refreshing, setRefreshing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [localConnection, setLocalConnection] = useState<ComposioConnection>(connection);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);

  async function doRefresh() {
    setRefreshing(true);
    setError(null);
    try {
      const updated = await refreshComposioConnection(localConnection.id);
      setLocalConnection(updated);
      onRefreshed(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Refresh failed");
    } finally {
      setRefreshing(false);
    }
  }

  async function doDelete() {
    setDeleting(true);
    setError(null);
    try {
      await deleteComposioConnection(localConnection.id);
      onDeleted(localConnection.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Disconnect failed");
      setDeleting(false);
    }
  }

  return (
    <div className="rounded-card border border-border px-3 py-2 space-y-1">
      <div className="flex items-center gap-2">
        <div className="flex-1 min-w-0 flex items-center gap-1.5">
          <p className="text-xs font-medium truncate">{localConnection.display_name}</p>
          <StatusPill status={localConnection.status} />
        </div>
        <div className="flex flex-shrink-0 gap-1">
          <button
            type="button"
            disabled={refreshing}
            onClick={() => void doRefresh()}
            aria-label={`Refresh connection ${localConnection.display_name}`}
            className="rounded-pill border border-border px-2 py-1 text-[10px] hover:bg-bg-app disabled:opacity-50"
          >
            {refreshing ? "…" : "Refresh"}
          </button>
          <button
            type="button"
            disabled={deleting}
            onClick={() => setConfirmDeleteOpen(true)}
            aria-label={`Disconnect ${localConnection.display_name}`}
            className="rounded-pill border border-bad/40 bg-bad/10 px-2 py-1 text-[10px] text-bad hover:bg-bad/20 disabled:opacity-50"
          >
            {deleting ? "…" : "Disconnect ✕"}
          </button>
        </div>
      </div>
      <p className="text-[9px] text-fg-muted">
        last checked: {relativeTime(localConnection.last_checked_at)}
      </p>
      {error && (
        <p className="text-[10px] text-bad">{error}</p>
      )}

      <ConfirmDialog
        open={confirmDeleteOpen}
        title={`Disconnect from ${localConnection.display_name}?`}
        description="This Composio connection will be removed. You can re-add it anytime."
        confirmLabel="Disconnect"
        variant="danger"
        onConfirm={() => {
          setConfirmDeleteOpen(false);
          void doDelete();
        }}
        onCancel={() => setConfirmDeleteOpen(false)}
      />
    </div>
  );
}
