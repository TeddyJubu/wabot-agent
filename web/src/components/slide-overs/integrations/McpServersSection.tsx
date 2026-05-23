import { useState } from "react";
import {
  checkMcpServer,
  deleteMcpServer,
  type McpServerRow,
} from "@/api/mcp";
import { AddMcpServerForm } from "./AddMcpServerForm";
import { EditMcpServerForm } from "./EditMcpServerForm";
import { RegistryBrowserModal } from "./RegistryBrowserModal";

interface Props {
  servers: McpServerRow[];
  onRefresh: () => void;
}

export function McpServersSection({ servers, onRefresh }: Props) {
  const [showAddForm, setShowAddForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [showRegistry, setShowRegistry] = useState(false);
  const [checkingId, setCheckingId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  // local health override after a manual check
  const [healthOverrides, setHealthOverrides] = useState<
    Record<number, { health_status: string; health_message: string | null; last_checked_at: string }>
  >({});

  async function doCheck(id: number) {
    setCheckingId(id);
    setError(null);
    try {
      const result = await checkMcpServer(id);
      setHealthOverrides((prev) => ({
        ...prev,
        [id]: {
          health_status: result.health_status,
          health_message: result.health_message,
          last_checked_at: new Date().toISOString(),
        },
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Check failed");
    } finally {
      setCheckingId(null);
    }
  }

  async function doDelete(id: number, name: string) {
    if (!window.confirm(`Delete MCP server "${name}"?`)) return;
    setDeletingId(id);
    setError(null);
    try {
      await deleteMcpServer(id);
      onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setDeletingId(null);
    }
  }

  const editingServer = servers.find((s) => s.id === editingId) ?? null;

  return (
    <section aria-label="MCP servers" className="space-y-3">
      {/* Section header */}
      <div className="flex items-center gap-2">
        <div className="h-px flex-1 bg-border" />
        <p className="text-[10px] font-medium uppercase tracking-wider text-fg-muted whitespace-nowrap">
          MCP servers ({servers.length} connected)
        </p>
        <div className="h-px flex-1 bg-border" />
      </div>

      {/* Action buttons */}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => { setShowAddForm((v) => !v); setEditingId(null); }}
          className="rounded-pill border border-border px-2.5 py-1 text-xs hover:bg-bg-app"
        >
          + Add server
        </button>
        <button
          type="button"
          onClick={() => setShowRegistry(true)}
          className="rounded-pill border border-border px-2.5 py-1 text-xs hover:bg-bg-app"
        >
          Browse registry
        </button>
      </div>

      {/* Error */}
      {error && (
        <p className="rounded-card border border-bad/40 bg-bad/10 px-3 py-2 text-xs text-bad">
          {error}
        </p>
      )}

      {/* Add form */}
      {showAddForm && !editingId && (
        <AddMcpServerForm
          onCreated={() => {
            setShowAddForm(false);
            onRefresh();
          }}
          onCancel={() => setShowAddForm(false)}
        />
      )}

      {/* Edit form */}
      {editingServer && (
        <EditMcpServerForm
          server={editingServer}
          onSaved={() => {
            setEditingId(null);
            onRefresh();
          }}
          onCancel={() => setEditingId(null)}
        />
      )}

      {/* Server rows */}
      {servers.length === 0 && !showAddForm ? (
        <p className="text-xs text-fg-muted">No MCP servers configured yet.</p>
      ) : (
        <div className="space-y-1.5">
          {servers.map((server) => {
            const override = healthOverrides[server.id];
            const status = override?.health_status ?? server.health_status;
            const checkedAt = override?.last_checked_at ?? server.last_checked_at;

            return (
              <ServerRow
                key={server.id}
                server={server}
                healthStatus={status}
                lastCheckedAt={checkedAt}
                checking={checkingId === server.id}
                deleting={deletingId === server.id}
                onCheck={() => void doCheck(server.id)}
                onEdit={() => { setEditingId(server.id); setShowAddForm(false); }}
                onDelete={() => void doDelete(server.id, server.name)}
              />
            );
          })}
        </div>
      )}

      {/* Registry modal */}
      {showRegistry && (
        <RegistryBrowserModal
          mode="mcp"
          onClose={() => setShowRegistry(false)}
          onInstalled={() => {
            setShowRegistry(false);
            onRefresh();
          }}
        />
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

interface ServerRowProps {
  server: McpServerRow;
  healthStatus: string | null;
  lastCheckedAt: string | null;
  checking: boolean;
  deleting: boolean;
  onCheck: () => void;
  onEdit: () => void;
  onDelete: () => void;
}

function ServerRow({
  server,
  healthStatus,
  lastCheckedAt,
  checking,
  deleting,
  onCheck,
  onEdit,
  onDelete,
}: ServerRowProps) {
  return (
    <div className="flex items-start gap-3 rounded-card border border-border px-3 py-2">
      <div className="flex-1 min-w-0 space-y-0.5">
        <div className="flex items-center gap-1.5">
          <HealthDot status={healthStatus} />
          <p className="text-xs font-medium truncate">{server.name}</p>
          <TransportPill transport={server.transport} />
        </div>
        {lastCheckedAt && (
          <p className="text-[9px] text-fg-muted">
            checked {new Date(lastCheckedAt).toLocaleTimeString()}
          </p>
        )}
      </div>
      <div className="flex flex-shrink-0 gap-1">
        <button
          type="button"
          disabled={checking}
          onClick={onCheck}
          aria-label={`Check server ${server.name}`}
          className="rounded-pill border border-border px-2 py-1 text-[10px] hover:bg-bg-app disabled:opacity-50"
        >
          {checking ? "…" : "Check"}
        </button>
        <button
          type="button"
          onClick={onEdit}
          aria-label={`Edit server ${server.name}`}
          className="rounded-pill border border-border px-2 py-1 text-[10px] hover:bg-bg-app"
        >
          Edit
        </button>
        <button
          type="button"
          disabled={deleting}
          onClick={onDelete}
          aria-label={`Delete server ${server.name}`}
          className="rounded-pill border border-bad/40 bg-bad/10 px-2 py-1 text-[10px] text-bad hover:bg-bad/20 disabled:opacity-50"
        >
          {deleting ? "…" : "Delete"}
        </button>
      </div>
    </div>
  );
}

function HealthDot({ status }: { status: string | null }) {
  let cls = "bg-fg-muted/40";
  let label = "unknown";
  if (status === "ok") { cls = "bg-green-400"; label = "healthy"; }
  else if (status === "error") { cls = "bg-red-400"; label = "error"; }

  return (
    <span
      aria-label={`Health: ${label}`}
      className={`inline-block size-2 rounded-full flex-shrink-0 ${cls}`}
    />
  );
}

function TransportPill({ transport }: { transport: string }) {
  return (
    <span className="rounded border border-border px-1.5 py-0.5 text-[9px] text-fg-muted">
      {transport}
    </span>
  );
}
