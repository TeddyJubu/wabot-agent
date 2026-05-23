import { useState } from "react";
import { createMcpServer, type McpServerRow } from "@/api/mcp";

interface Props {
  onCreated: (server: McpServerRow) => void;
  onCancel: () => void;
}

export function AddMcpServerForm({ onCreated, onCancel }: Props) {
  const [name, setName] = useState("");
  const [transport, setTransport] = useState("stdio");
  const [configJson, setConfigJson] = useState("{}");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [jsonError, setJsonError] = useState<string | null>(null);

  function validateJson(value: string): boolean {
    try {
      JSON.parse(value);
      setJsonError(null);
      return true;
    } catch {
      setJsonError("Invalid JSON");
      return false;
    }
  }

  function handleConfigChange(value: string) {
    setConfigJson(value);
    if (value.trim()) validateJson(value);
    else setJsonError(null);
  }

  const canSubmit = name.trim().length > 0 && configJson.trim().length > 0 && !jsonError;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!validateJson(configJson)) return;
    let parsedConfig: Record<string, unknown>;
    try {
      parsedConfig = JSON.parse(configJson) as Record<string, unknown>;
    } catch {
      setJsonError("Invalid JSON");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const server = await createMcpServer({ name: name.trim(), transport, config_json: parsedConfig });
      onCreated(server);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={(e) => void handleSubmit(e)} className="space-y-3 rounded-card border border-border bg-bg-app px-3 py-3">
      <p className="text-[10px] font-medium uppercase tracking-wider text-fg-muted">Add MCP server</p>

      {error && (
        <p className="rounded-card border border-bad/40 bg-bad/10 px-3 py-2 text-xs text-bad">
          {error}
        </p>
      )}

      <div className="space-y-1">
        <label className="text-[10px] text-fg-muted" htmlFor="mcp-name">Name</label>
        <input
          id="mcp-name"
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="my-mcp-server"
          className="w-full rounded-card border border-border bg-bg-card px-3 py-2 text-xs"
        />
      </div>

      <div className="space-y-1">
        <label className="text-[10px] text-fg-muted" htmlFor="mcp-transport">Transport</label>
        <select
          id="mcp-transport"
          value={transport}
          onChange={(e) => setTransport(e.target.value)}
          className="w-full rounded-card border border-border bg-bg-card px-3 py-2 text-xs"
        >
          <option value="stdio">stdio</option>
          <option value="http">http</option>
        </select>
      </div>

      <div className="space-y-1">
        <label className="text-[10px] text-fg-muted" htmlFor="mcp-config">
          Config JSON
        </label>
        <textarea
          id="mcp-config"
          value={configJson}
          onChange={(e) => handleConfigChange(e.target.value)}
          rows={4}
          placeholder='{"command": "npx", "args": ["-y", "my-mcp"]}'
          className={`w-full rounded-card border bg-bg-card px-3 py-2 font-mono text-xs ${
            jsonError ? "border-bad" : "border-border"
          }`}
          aria-label="Config JSON"
        />
        {jsonError && (
          <p className="text-[10px] text-bad">{jsonError}</p>
        )}
      </div>

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={!canSubmit || submitting}
          className="rounded-pill border border-accent bg-accent/10 px-3 py-1.5 text-xs font-medium text-accent disabled:opacity-50"
        >
          {submitting ? "Adding…" : "Add server"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-pill border border-border px-3 py-1.5 text-xs text-fg-muted hover:bg-bg-card"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
