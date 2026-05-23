import { useEffect, useRef, useState } from "react";
import {
  searchSkillRegistry,
  installSkillFromRegistry,
  type SkillRegistryEntry,
} from "@/api/skills";
import {
  searchMcpRegistry,
  installMcpFromRegistry,
  type McpRegistryEntry,
} from "@/api/mcp";

interface Props {
  mode: "skills" | "mcp";
  onClose: () => void;
  onInstalled: () => void;
}

export function RegistryBrowserModal({ mode, onClose, onInstalled }: Props) {
  const [query, setQuery] = useState("");
  const [skillResults, setSkillResults] = useState<SkillRegistryEntry[]>([]);
  const [mcpResults, setMcpResults] = useState<McpRegistryEntry[]>([]);
  const [searching, setSearching] = useState(false);
  const [installing, setInstalling] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [successId, setSuccessId] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    // Load initial results on mount
    void doSearch("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function scheduleSearch(q: string) {
    setQuery(q);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => void doSearch(q), 300);
  }

  async function doSearch(q: string) {
    setSearching(true);
    setError(null);
    try {
      if (mode === "skills") {
        const res = await searchSkillRegistry(q);
        setSkillResults(res);
      } else {
        const res = await searchMcpRegistry(q);
        setMcpResults(res);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed");
    } finally {
      setSearching(false);
    }
  }

  async function doInstall(id: string) {
    setInstalling(id);
    setError(null);
    try {
      if (mode === "skills") {
        await installSkillFromRegistry(id);
      } else {
        await installMcpFromRegistry(id);
      }
      setSuccessId(id);
      onInstalled();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Install failed");
    } finally {
      setInstalling(null);
    }
  }

  const title = mode === "skills" ? "Browse skill registry" : "Browse MCP registry";

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="flex w-full max-w-md flex-col rounded-card border border-border bg-bg-card shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close modal"
            className="grid size-7 place-items-center rounded text-fg-muted hover:bg-bg-app hover:text-fg"
          >
            ×
          </button>
        </div>

        {/* Search */}
        <div className="border-b border-border px-4 py-3">
          <input
            type="search"
            placeholder="Search…"
            value={query}
            onChange={(e) => scheduleSearch(e.target.value)}
            className="w-full rounded-card border border-border bg-bg-app px-3 py-2 text-xs"
            aria-label="Search registry"
          />
        </div>

        {/* Error */}
        {error && (
          <p className="mx-4 mt-3 rounded-card border border-bad/40 bg-bad/10 px-3 py-2 text-xs text-bad">
            {error}
          </p>
        )}

        {/* Results */}
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2 max-h-96">
          {searching && (
            <p className="text-xs text-fg-muted">Searching…</p>
          )}

          {!searching && mode === "skills" && skillResults.length === 0 && (
            <p className="text-xs text-fg-muted">No results.</p>
          )}

          {!searching && mode === "mcp" && mcpResults.length === 0 && (
            <p className="text-xs text-fg-muted">No results.</p>
          )}

          {mode === "skills" &&
            skillResults.map((entry) => (
              <SkillResultRow
                key={entry.id}
                entry={entry}
                installing={installing === entry.id}
                installed={successId === entry.id}
                onInstall={() => void doInstall(entry.id)}
              />
            ))}

          {mode === "mcp" &&
            mcpResults.map((entry) => (
              <McpResultRow
                key={entry.id}
                entry={entry}
                installing={installing === entry.id}
                installed={successId === entry.id}
                onInstall={() => void doInstall(entry.id)}
              />
            ))}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Row sub-components
// ---------------------------------------------------------------------------

interface SkillRowProps {
  entry: SkillRegistryEntry;
  installing: boolean;
  installed: boolean;
  onInstall: () => void;
}

function SkillResultRow({ entry, installing, installed, onInstall }: SkillRowProps) {
  return (
    <div className="flex items-start gap-3 rounded-card border border-border px-3 py-2">
      <div className="flex-1 min-w-0 space-y-0.5">
        <p className="text-xs font-medium truncate">{entry.name}</p>
        {entry.description && (
          <p className="text-[10px] text-fg-muted line-clamp-2">{entry.description}</p>
        )}
        {entry.version && (
          <span className="inline-block rounded border border-border px-1.5 py-0.5 text-[9px] text-fg-muted">
            v{entry.version}
          </span>
        )}
      </div>
      <button
        type="button"
        disabled={installing || installed}
        onClick={onInstall}
        className="flex-shrink-0 rounded-pill border border-border px-2.5 py-1 text-[10px] font-medium hover:bg-bg-app disabled:opacity-50"
      >
        {installed ? "Installed" : installing ? "Installing…" : "Install"}
      </button>
    </div>
  );
}

interface McpRowProps {
  entry: McpRegistryEntry;
  installing: boolean;
  installed: boolean;
  onInstall: () => void;
}

function McpResultRow({ entry, installing, installed, onInstall }: McpRowProps) {
  return (
    <div className="flex items-start gap-3 rounded-card border border-border px-3 py-2">
      <div className="flex-1 min-w-0 space-y-0.5">
        <div className="flex items-center gap-1.5">
          <p className="text-xs font-medium truncate">{entry.name}</p>
          <SourcePill source={entry.source} />
        </div>
        {entry.description && (
          <p className="text-[10px] text-fg-muted line-clamp-2">{entry.description}</p>
        )}
        {entry.transport_hint && (
          <span className="inline-block rounded border border-border px-1.5 py-0.5 text-[9px] text-fg-muted">
            {entry.transport_hint}
          </span>
        )}
      </div>
      <button
        type="button"
        disabled={installing || installed}
        onClick={onInstall}
        className="flex-shrink-0 rounded-pill border border-border px-2.5 py-1 text-[10px] font-medium hover:bg-bg-app disabled:opacity-50"
      >
        {installed ? "Installed" : installing ? "Installing…" : "Install"}
      </button>
    </div>
  );
}

interface SourcePillProps {
  source: "curated" | "composio";
}

export function SourcePill({ source }: SourcePillProps) {
  return (
    <span
      className={`inline-block rounded border px-1.5 py-0.5 text-[9px] font-medium ${
        source === "curated"
          ? "border-green-500/40 bg-green-500/10 text-green-400"
          : "border-blue-500/40 bg-blue-500/10 text-blue-400"
      }`}
    >
      {source}
    </span>
  );
}
