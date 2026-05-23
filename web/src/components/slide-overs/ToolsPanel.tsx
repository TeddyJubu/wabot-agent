import { useEffect, useRef, useState } from "react";
import {
  listTools,
  refreshTools,
  toggleTool,
  type ToolRow,
  type ToolKind,
  type ToolsListResponse,
} from "@/api/tools";

const TABS: { kind: ToolKind; label: string }[] = [
  { kind: "native", label: "Native" },
  { kind: "mcp", label: "MCP" },
  { kind: "composio", label: "Composio" },
  { kind: "skill_action", label: "Skills" },
];

const EMPTY_STATE_MESSAGES: Record<ToolKind, string> = {
  native: "No native tools found. Run Refresh to scan.",
  mcp: "No MCP tools. Connect an MCP server in Phase 4 (Integrations).",
  composio: "No Composio tools. Connect Composio in Phase 5 (Integrations).",
  skill_action: "No skill actions. Skills install in Phase 4.",
};

interface ToolRowItemProps {
  tool: ToolRow;
  onToggle: (id: number, enabled: boolean) => void;
  toggling: boolean;
}

function ToolRowItem({ tool, onToggle, toggling }: ToolRowItemProps) {
  return (
    <div className="flex items-start gap-3 rounded-card border border-border px-3 py-2">
      <div className="flex-1 min-w-0 space-y-0.5">
        <p className="text-xs font-medium truncate">{tool.name}</p>
        {tool.description && (
          <p className="text-[10px] text-fg-muted line-clamp-1">{tool.description}</p>
        )}
        {tool.is_assigned_to.length > 0 && (
          <div className="flex flex-wrap gap-1 pt-0.5">
            {tool.is_assigned_to.map((slug) => (
              <span
                key={slug}
                className="rounded border border-border px-1.5 py-0.5 text-[9px] text-fg-muted"
              >
                {slug}
              </span>
            ))}
          </div>
        )}
      </div>
      <button
        type="button"
        disabled={toggling}
        onClick={() => onToggle(tool.id, !tool.is_enabled)}
        className={`flex-shrink-0 rounded-pill border px-2.5 py-1 text-[10px] font-medium transition disabled:opacity-50 ${
          tool.is_enabled
            ? "border-green-500/40 bg-green-500/10 text-green-400"
            : "border-border text-fg-muted"
        }`}
      >
        {tool.is_enabled ? "on" : "off"}
      </button>
    </div>
  );
}

export default function ToolsPanel() {
  const [data, setData] = useState<ToolsListResponse | null>(null);
  const [activeTab, setActiveTab] = useState<ToolKind>("native");
  const [search, setSearch] = useState("");
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshMsg, setRefreshMsg] = useState<string | null>(null);
  const [refreshBannerVisible, setRefreshBannerVisible] = useState(false);
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [toggling, setToggling] = useState<Set<number>>(new Set());
  const [toggleError, setToggleError] = useState<string | null>(null);

  useEffect(() => {
    void load();
  }, []);

  // Clean up auto-dismiss timer on unmount
  useEffect(() => {
    return () => {
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    };
  }, []);

  async function load() {
    setState("loading");
    setError(null);
    try {
      setData(await listTools());
      setState("ready");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load tools");
      setState("error");
    }
  }

  function showRefreshBanner(msg: string) {
    setRefreshMsg(msg);
    setRefreshBannerVisible(true);
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    refreshTimerRef.current = setTimeout(() => {
      setRefreshBannerVisible(false);
    }, 8000);
  }

  function dismissRefreshBanner() {
    setRefreshBannerVisible(false);
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current);
      refreshTimerRef.current = null;
    }
  }

  async function doRefresh() {
    setRefreshing(true);
    setRefreshMsg(null);
    setRefreshBannerVisible(false);
    try {
      const res = await refreshTools();
      const total = res.native_added + res.composio_added + res.mcp_added;
      if (total === 0) {
        showRefreshBanner("No changes — catalog is up to date.");
      } else {
        const parts: string[] = [];
        if (res.native_added > 0) parts.push(`${res.native_added} native added`);
        if (res.composio_added > 0) parts.push(`${res.composio_added} composio added`);
        if (res.mcp_added > 0) parts.push(`${res.mcp_added} MCP added`);
        showRefreshBanner(parts.join(" · "));
      }
      setData(await listTools());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Refresh failed");
    } finally {
      setRefreshing(false);
    }
  }

  async function doToggle(id: number, enabled: boolean) {
    setToggling((prev) => new Set(prev).add(id));
    // Optimistic update
    setData((prev) => {
      if (!prev) return prev;
      function patchRow(rows: ToolRow[]) {
        return rows.map((r) => (r.id === id ? { ...r, is_enabled: enabled } : r));
      }
      return {
        native: patchRow(prev.native),
        mcp: patchRow(prev.mcp),
        composio: patchRow(prev.composio),
        skill_action: patchRow(prev.skill_action),
      };
    });
    try {
      const updated = await toggleTool(id, enabled);
      // Reconcile with server value
      setData((prev) => {
        if (!prev) return prev;
        function patchRow(rows: ToolRow[]) {
          return rows.map((r) => (r.id === id ? updated : r));
        }
        return {
          native: patchRow(prev.native),
          mcp: patchRow(prev.mcp),
          composio: patchRow(prev.composio),
          skill_action: patchRow(prev.skill_action),
        };
      });
    } catch (err) {
      // Revert optimistic update on failure
      setData((prev) => {
        if (!prev) return prev;
        function patchRow(rows: ToolRow[]) {
          return rows.map((r) => (r.id === id ? { ...r, is_enabled: !enabled } : r));
        }
        return {
          native: patchRow(prev.native),
          mcp: patchRow(prev.mcp),
          composio: patchRow(prev.composio),
          skill_action: patchRow(prev.skill_action),
        };
      });
      setToggleError(err instanceof Error ? err.message : "Toggle failed");
    } finally {
      setToggling((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  }

  const currentRows = data ? data[activeTab] : [];
  const q = search.toLowerCase();
  const filtered = currentRows.filter(
    (t) =>
      t.name.toLowerCase().includes(q) ||
      (t.description ?? "").toLowerCase().includes(q),
  );

  function tabCount(kind: ToolKind) {
    return data ? data[kind].length : 0;
  }

  return (
    <div className="space-y-3">
      {/* Refresh button row */}
      <div className="flex items-center justify-between">
        <p className="text-[10px] font-medium uppercase tracking-wider text-fg-muted">
          {state === "loading" ? "Loading…" : "Tool catalog"}
        </p>
        <button
          type="button"
          disabled={refreshing || state === "loading"}
          onClick={() => void doRefresh()}
          className="rounded-pill border border-border px-2.5 py-1 text-xs hover:bg-bg-app disabled:opacity-50"
        >
          {refreshing ? "Refreshing…" : "↻ Refresh"}
        </button>
      </div>

      {refreshMsg && refreshBannerVisible && (
        <div className="flex items-center justify-between rounded-card border border-border bg-bg-app px-3 py-2 text-[10px] text-fg-muted">
          <span>{refreshMsg}</span>
          <button
            type="button"
            onClick={dismissRefreshBanner}
            aria-label="Dismiss"
            className="ml-2 text-fg-muted hover:text-fg leading-none"
          >
            ×
          </button>
        </div>
      )}

      {error && (
        <p className="rounded-card border border-bad/40 bg-bad/10 px-3 py-2 text-xs text-bad">
          {error}
        </p>
      )}

      {toggleError && (
        <p className="rounded-card border border-bad/40 bg-bad/10 px-3 py-2 text-xs text-bad">
          {toggleError}
        </p>
      )}

      {/* Tab bar */}
      <div className="flex flex-wrap gap-1">
        {TABS.map((tab) => (
          <button
            key={tab.kind}
            type="button"
            onClick={() => {
              setActiveTab(tab.kind);
              setSearch("");
            }}
            className={`rounded-pill border px-2.5 py-1 text-xs transition ${
              activeTab === tab.kind
                ? "border-accent bg-accent/10 text-accent"
                : "border-border text-fg-muted hover:bg-bg-app"
            }`}
          >
            {tab.label} ({tabCount(tab.kind)})
          </button>
        ))}
      </div>

      {/* Search */}
      <input
        type="search"
        placeholder="Filter tools…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="w-full rounded-card border border-border bg-bg-app px-3 py-2 text-xs"
      />

      {/* List */}
      {state === "loading" && (
        <p className="text-xs text-fg-muted">Loading tools…</p>
      )}

      {state === "ready" && filtered.length === 0 && (
        <p className="text-xs text-fg-muted">
          {search ? "No tools match your filter." : EMPTY_STATE_MESSAGES[activeTab]}
        </p>
      )}

      {state === "ready" && (
        <div className="space-y-1.5">
          {filtered.map((t) => (
            <ToolRowItem
              key={t.id}
              tool={t}
              onToggle={(id, enabled) => void doToggle(id, enabled)}
              toggling={toggling.has(t.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
