import { useEffect, useState } from "react";
import { fetchRuns, type Run } from "@/api/runs";

export default function RunsPanel() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    fetchRuns()
      .then((r) => {
        setRuns(r);
        setState("ready");
      })
      .catch(() => setState("error"));
  }, []);

  if (state === "loading") return <p className="text-xs text-fg-muted">Loading runs…</p>;
  if (state === "error") return <p className="text-xs text-bad">Couldn't load runs.</p>;
  if (runs.length === 0) return <p className="text-xs text-fg-muted">No runs yet.</p>;

  return (
    <ul className="space-y-2">
      {runs.map((r) => (
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
          <p className="mt-1.5 truncate text-sm">{r.user_input || "(no input)"}</p>
          {r.final_output && (
            <p className="mt-1 line-clamp-2 text-xs text-fg-muted">{r.final_output}</p>
          )}
        </li>
      ))}
    </ul>
  );
}
