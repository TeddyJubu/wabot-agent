import { useEffect, useRef, useState } from "react";
import {
  createComposioConnection,
  listComposioConnections,
  type ComposioApp,
  type ComposioConnection,
} from "@/api/composio";

interface Props {
  apps: ComposioApp[];
  /** Notify parent that a new connection was created/resolved */
  onConnectionCreated: (conn: ComposioConnection) => void;
}

const POLL_INTERVAL_MS = 3000;
const POLL_TIMEOUT_MS = 60000;

export function ComposioAppsList({ apps, onConnectionCreated }: Props) {
  const [search, setSearch] = useState("");
  const [connecting, setConnecting] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  // pendingSlug drives the polling useEffect
  const [pendingSlug, setPendingSlug] = useState<{ slug: string; connId: number } | null>(null);
  // Stable ref to onConnectionCreated so the effect closure doesn't go stale
  const onConnectionCreatedRef = useRef(onConnectionCreated);
  useEffect(() => {
    onConnectionCreatedRef.current = onConnectionCreated;
  });

  // Polling loop — starts when pendingSlug is set, cleans up on unmount or when cleared
  useEffect(() => {
    if (pendingSlug === null) return;

    let cancelled = false;
    const { slug, connId } = pendingSlug;
    const deadline = Date.now() + POLL_TIMEOUT_MS;

    async function runPoll() {
      while (!cancelled) {
        if (Date.now() > deadline) {
          if (!cancelled) {
            setConnecting(null);
            setPendingSlug(null);
          }
          return;
        }
        await new Promise<void>((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
        if (cancelled) return;

        try {
          const connections = await listComposioConnections();
          if (cancelled) return;
          const found = connections.find((c) => c.id === connId);
          if (found && found.status === "connected") {
            onConnectionCreatedRef.current(found);
            if (!cancelled) {
              setConnecting(null);
              setPendingSlug(null);
            }
            return;
          }
        } catch {
          // network blip — keep polling
          if (cancelled) return;
        }
      }
    }

    void runPoll();

    return () => {
      cancelled = true;
      // Clear connecting state only if this slug is still the active one
      setConnecting((prev) => (prev === slug ? null : prev));
    };
  }, [pendingSlug]);

  const filtered = apps.filter((app) => {
    const q = search.toLowerCase();
    return (
      app.name.toLowerCase().includes(q) ||
      app.slug.toLowerCase().includes(q) ||
      (app.description ?? "").toLowerCase().includes(q)
    );
  });

  async function doConnect(app: ComposioApp) {
    setConnecting(app.slug);
    setErrors((prev) => ({ ...prev, [app.slug]: "" }));

    try {
      const created = await createComposioConnection({ app_slug: app.slug });

      if (created.redirect_url) {
        window.open(created.redirect_url, "_blank", "noopener,noreferrer");
      }

      // Hand off to the useEffect-based polling loop
      setPendingSlug({ slug: app.slug, connId: created.id });
    } catch (err) {
      setErrors((prev) => ({
        ...prev,
        [app.slug]: err instanceof Error ? err.message : "Connect failed",
      }));
      setConnecting(null);
    }
  }

  return (
    <div className="space-y-2">
      <input
        type="search"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search apps…"
        aria-label="Search available apps"
        className="w-full rounded-card border border-border bg-bg-app px-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-border"
      />

      {filtered.length === 0 ? (
        <p className="text-xs text-fg-muted">No apps found.</p>
      ) : (
        <div className="space-y-1.5">
          {filtered.map((app) => (
            <div key={app.slug} className="flex items-start gap-2 rounded-card border border-border px-3 py-2">
              {app.logo_url ? (
                <img
                  src={app.logo_url}
                  alt={app.name}
                  className="size-5 flex-shrink-0 rounded object-contain mt-0.5"
                />
              ) : (
                <span className="size-5 flex-shrink-0 rounded bg-border/40 mt-0.5" />
              )}
              <div className="flex-1 min-w-0 space-y-0.5">
                <p className="text-xs font-medium truncate">{app.name}</p>
                {app.description && (
                  <p className="text-[10px] text-fg-muted line-clamp-1">{app.description}</p>
                )}
                {app.categories.length > 0 && (
                  <p className="text-[9px] text-fg-muted">
                    {app.categories.join(", ")}
                  </p>
                )}
                {errors[app.slug] && (
                  <p className="text-[10px] text-bad">{errors[app.slug]}</p>
                )}
              </div>
              <button
                type="button"
                disabled={connecting === app.slug}
                onClick={() => void doConnect(app)}
                aria-label={`Connect ${app.name}`}
                className="flex-shrink-0 rounded-pill border border-border px-2.5 py-1 text-[10px] hover:bg-bg-app disabled:opacity-50"
              >
                {connecting === app.slug ? "Connecting…" : "Connect"}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
