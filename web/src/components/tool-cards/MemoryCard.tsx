import { Brain } from "lucide-react";
import type { ToolAction, MemoryData } from "@/types/ui-envelope";

interface Props {
  data: MemoryData;
  actions: ToolAction[];
  onAction: (id: string) => void;
}

export default function MemoryCard({ data, actions, onAction }: Props) {
  return (
    <div className="rounded-card border border-border bg-bg-card p-4 shadow-sm">
      <div className="flex items-start gap-3">
        <Brain className="mt-0.5 size-5 text-accent" aria-hidden />
        <div className="flex-1">
          <div className="flex items-baseline justify-between gap-3">
            <h3 className="text-sm font-medium">Contact memory</h3>
            <span className="font-mono text-xs text-fg-muted">{data.contact_masked}</span>
          </div>
          {data.facts.length === 0 ? (
            <p className="mt-2 text-xs text-fg-muted">No facts recorded yet.</p>
          ) : (
            <ul className="mt-2 flex flex-wrap gap-1.5">
              {data.facts.map((f) => (
                <li
                  key={f.id}
                  className="rounded-pill border border-border bg-bg-app px-2.5 py-1 text-xs"
                >
                  {f.text}
                </li>
              ))}
            </ul>
          )}
          {actions.length > 0 && (
            <div className="mt-3 flex gap-2">
              {actions.map((a) => (
                <button
                  key={a.id}
                  onClick={() => onAction(a.id)}
                  className="rounded-pill border border-border px-2.5 py-1 text-xs hover:bg-bg-app"
                >
                  {a.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
