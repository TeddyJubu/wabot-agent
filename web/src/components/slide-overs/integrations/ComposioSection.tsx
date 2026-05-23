import { useEffect, useState } from "react";
import {
  getComposioStatus,
  listComposioApps,
  listComposioConnections,
  type ComposioStatus,
  type ComposioApp,
  type ComposioConnection,
} from "@/api/composio";
import { ComposioApiKeyForm } from "./composio/ComposioApiKeyForm";
import { ComposioConnectionRow } from "./composio/ComposioConnectionRow";
import { ComposioAppsList } from "./composio/ComposioAppsList";

export function ComposioSection() {
  const [status, setStatus] = useState<ComposioStatus | null>(null);
  const [apps, setApps] = useState<ComposioApp[]>([]);
  const [connections, setConnections] = useState<ComposioConnection[]>([]);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showChangeKey, setShowChangeKey] = useState(false);
  const [showApps, setShowApps] = useState(false);

  useEffect(() => {
    void load();
  }, []);

  async function load() {
    setLoadState("loading");
    setLoadError(null);
    try {
      const s = await getComposioStatus();
      setStatus(s);
      if (s.api_key_present) {
        const [a, c] = await Promise.all([listComposioApps(), listComposioConnections()]);
        setApps(a);
        setConnections(c);
      }
      setLoadState("ready");
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Could not load Composio status");
      setLoadState("error");
    }
  }

  async function refreshConnections() {
    try {
      const c = await listComposioConnections();
      setConnections(c);
    } catch {
      // silently ignore
    }
  }

  function handleSaved(newStatus: ComposioStatus) {
    setStatus(newStatus);
    setShowChangeKey(false);
    if (newStatus.api_key_present) {
      void Promise.all([listComposioApps(), listComposioConnections()]).then(([a, c]) => {
        setApps(a);
        setConnections(c);
      });
    }
  }

  function handleConnectionRefreshed(updated: ComposioConnection) {
    setConnections((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
  }

  function handleConnectionDeleted(id: number) {
    setConnections((prev) => prev.filter((c) => c.id !== id));
  }

  function handleConnectionCreated(conn: ComposioConnection) {
    setConnections((prev) => {
      const exists = prev.find((c) => c.id === conn.id);
      if (exists) return prev.map((c) => (c.id === conn.id ? conn : c));
      return [...prev, conn];
    });
  }

  const statusLabel =
    status == null
      ? ""
      : !status.api_key_present
        ? "not connected"
        : status.last_error
          ? "error"
          : "connected";

  return (
    <section aria-label="Composio" className="space-y-3">
      {/* Section header */}
      <div className="flex items-center gap-2">
        <div className="h-px flex-1 bg-border" />
        <p className="text-[10px] font-medium uppercase tracking-wider text-fg-muted whitespace-nowrap">
          Composio{statusLabel ? ` (status: ${statusLabel})` : ""}
        </p>
        <div className="h-px flex-1 bg-border" />
      </div>

      {loadState === "loading" && (
        <p className="text-xs text-fg-muted">Loading Composio…</p>
      )}

      {loadState === "error" && loadError && (
        <p className="rounded-card border border-bad/40 bg-bad/10 px-3 py-2 text-xs text-bad">
          {loadError}
        </p>
      )}

      {loadState === "ready" && status && !status.api_key_present && !showChangeKey && (
        <div className="space-y-2">
          <p className="text-xs text-fg-muted">Composio is not configured.</p>
          <ComposioApiKeyForm onSaved={handleSaved} />
        </div>
      )}

      {loadState === "ready" && status && status.api_key_present && (
        <div className="space-y-4">
          {/* Connected status line */}
          <div className="flex items-center justify-between gap-2">
            <p className="text-[10px] text-fg-muted">
              Composio connected as user:{" "}
              <span className="font-mono">{status.user_id ?? "shared"}</span>
            </p>
            {!showChangeKey && (
              <button
                type="button"
                onClick={() => setShowChangeKey(true)}
                className="rounded-pill border border-border px-2.5 py-1 text-[10px] hover:bg-bg-app"
              >
                Change API key
              </button>
            )}
          </div>

          {showChangeKey && (
            <ComposioApiKeyForm
              onSaved={handleSaved}
              onCancel={() => setShowChangeKey(false)}
            />
          )}

          {/* Connected apps */}
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <div className="h-px flex-1 bg-border" />
              <p className="text-[9px] font-medium uppercase tracking-wider text-fg-muted whitespace-nowrap">
                Connected apps ({connections.length})
              </p>
              <div className="h-px flex-1 bg-border" />
            </div>

            {connections.length === 0 ? (
              <p className="text-xs text-fg-muted">No apps connected yet.</p>
            ) : (
              <div className="space-y-1.5">
                {connections.map((conn) => (
                  <ComposioConnectionRow
                    key={conn.id}
                    connection={conn}
                    onRefreshed={handleConnectionRefreshed}
                    onDeleted={handleConnectionDeleted}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Available apps (collapsible) */}
          <div className="space-y-2">
            <button
              type="button"
              onClick={() => setShowApps((v) => !v)}
              className="flex w-full items-center gap-2 text-left"
            >
              <div className="h-px flex-1 bg-border" />
              <p className="text-[9px] font-medium uppercase tracking-wider text-fg-muted whitespace-nowrap">
                Available apps ({apps.length}) {showApps ? "▲" : "▼"}
              </p>
              <div className="h-px flex-1 bg-border" />
            </button>

            {showApps && (
              <ComposioAppsList
                apps={apps}
                onConnectionCreated={(conn) => {
                  handleConnectionCreated(conn);
                  void refreshConnections();
                }}
              />
            )}
          </div>
        </div>
      )}
    </section>
  );
}
