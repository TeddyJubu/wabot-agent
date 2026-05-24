import { useEffect, useState } from "react";
import { fetchRuns, type Run } from "@/api/runs";

export function InboxTab() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    fetchRuns(100)
      .then((data) => {
        setRuns(data);
        setState("ready");
      })
      .catch(() => setState("error"));
  }, []);

  if (state === "loading") return <p className="text-xs text-fg-muted">Loading inbox…</p>;
  if (state === "error") return <p className="text-xs text-bad">Couldn't load inbox.</p>;

  // Inbound messages: runs that have user_input (they represent inbound messages)
  const inbound = runs.filter((r) => r.user_input);

  if (inbound.length === 0) {
    return <p className="text-xs text-fg-muted">No inbound messages yet.</p>;
  }

  return (
    <ul className="space-y-2">
      {inbound.map((r) => (
        <li key={r.run_id} className="rounded-card border border-border p-3">
          <div className="flex items-center justify-between text-xs">
            {r.sender ? (
              <span className="font-medium">{r.sender}</span>
            ) : (
              <span className="text-fg-muted">Unknown sender</span>
            )}
            <span className="text-fg-muted">
              {new Date(r.created_at).toLocaleString(undefined, {
                month: "short",
                day: "numeric",
                hour: "2-digit",
                minute: "2-digit",
              })}
            </span>
          </div>
          <p className="mt-1.5 text-sm">{r.user_input}</p>
          {r.final_output && (
            <div className="mt-2 rounded border-l-2 border-accent/40 pl-2">
              <p className="line-clamp-2 text-xs text-fg-muted">
                <span className="text-fg-muted font-medium">Reply · </span>
                {r.final_output}
              </p>
              <p className="mt-0.5 text-xs text-fg-muted/60 font-mono">
                run:{r.run_id.slice(0, 8)}
              </p>
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}
