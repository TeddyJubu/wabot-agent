import { useEffect, useState, useCallback } from "react";
import { fetchRuns, type Run } from "@/api/runs";
import { RunsFilters } from "./RunsFilters";

// Phase 6 review SHOULD FIX 2: WhatsApp message text can contain PII.
// Truncate user_input and final_output by default; user clicks "show
// full" to expand individual rows. CSS truncation alone (truncate /
// line-clamp) still puts the full string in the DOM where it shows on
// hover and gets copied with Cmd-A.
const USER_INPUT_PREVIEW_CHARS = 80;
const FINAL_OUTPUT_PREVIEW_CHARS = 120;

function truncate(s: string, n: number): { text: string; truncated: boolean } {
  if (s.length <= n) return { text: s, truncated: false };
  return { text: s.slice(0, n) + "…", truncated: true };
}

export function RunsTab() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  // Filters
  const [agentFilter, setAgentFilter] = useState("");
  const [windowFilter, setWindowFilter] = useState<"1h" | "24h" | "7d">("24h");
  const [statusFilter, setStatusFilter] = useState<"all" | "errored">("all");

  function toggleExpand(runId: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(runId)) next.delete(runId);
      else next.add(runId);
      return next;
    });
  }

  const load = useCallback(async () => {
    setState("loading");
    try {
      const data = await fetchRuns(100);
      setRuns(data);
      setState("ready");
    } catch {
      setState("error");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const allAgents = Array.from(new Set(runs.map((r) => r.sender).filter(Boolean) as string[]));

  // Client-side filtering (the backend currently doesn't expose filter params — filter locally)
  const now = Date.now();
  const windowMs: Record<"1h" | "24h" | "7d", number> = {
    "1h": 60 * 60 * 1000,
    "24h": 24 * 60 * 60 * 1000,
    "7d": 7 * 24 * 60 * 60 * 1000,
  };

  const filtered = runs.filter((r) => {
    if (agentFilter && r.sender !== agentFilter) return false;
    const age = now - new Date(r.created_at).getTime();
    if (age > windowMs[windowFilter]) return false;
    // "errored" = final_output contains an error marker (heuristic)
    if (statusFilter === "errored" && !r.final_output?.toLowerCase().includes("error")) return false;
    return true;
  });

  if (state === "loading") {
    return <p className="text-xs text-fg-muted">Loading runs…</p>;
  }
  if (state === "error") {
    return <p className="text-xs text-bad">Couldn't load runs.</p>;
  }

  return (
    <div>
      <RunsFilters
        agents={allAgents}
        agentFilter={agentFilter}
        windowFilter={windowFilter}
        statusFilter={statusFilter}
        onAgentChange={setAgentFilter}
        onWindowChange={setWindowFilter}
        onStatusChange={setStatusFilter}
      />

      {filtered.length === 0 ? (
        <p className="text-xs text-fg-muted">No runs match your filters.</p>
      ) : (
        <ul className="space-y-2">
          {filtered.map((r) => {
            const isExpanded = expanded.has(r.run_id);
            const userInputRaw = r.user_input || "";
            const finalOutputRaw = r.final_output || "";
            const userInput = isExpanded
              ? { text: userInputRaw, truncated: false }
              : truncate(userInputRaw, USER_INPUT_PREVIEW_CHARS);
            const finalOutput = isExpanded
              ? { text: finalOutputRaw, truncated: false }
              : truncate(finalOutputRaw, FINAL_OUTPUT_PREVIEW_CHARS);
            const anyTruncated = userInput.truncated || finalOutput.truncated;
            return (
              <li key={r.run_id} className="rounded-card border border-border p-3">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-mono text-fg-muted">{r.run_id.slice(0, 8)}</span>
                  <span className="text-fg-muted">
                    {new Date(r.created_at).toLocaleString(undefined, {
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </span>
                </div>
                {r.sender && (
                  <p className="mt-0.5 text-xs text-fg-muted">{r.sender}</p>
                )}
                <p className="mt-1.5 text-sm whitespace-pre-wrap break-words">
                  {userInput.text || "(no input)"}
                </p>
                {finalOutputRaw && (
                  <p className="mt-1 text-xs text-fg-muted whitespace-pre-wrap break-words">
                    {finalOutput.text}
                  </p>
                )}
                {(anyTruncated || isExpanded) && (
                  <button
                    type="button"
                    onClick={() => toggleExpand(r.run_id)}
                    className="mt-1.5 text-xs text-accent hover:underline"
                  >
                    {isExpanded ? "show less" : "show full"}
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
