import { MessageSquare } from "lucide-react";
import type { InboxMessageData, ToolAction } from "@/types/ui-envelope";

interface Props {
  data: InboxMessageData;
  actions: ToolAction[];
}

export default function InboxMessageCard({ data }: Props) {
  const items = data.messages ?? [];
  return (
    <div className="rounded-card border border-border bg-bg-card p-4 shadow-sm">
      <div className="flex items-start gap-3">
        <MessageSquare className="mt-0.5 size-5 text-accent" aria-hidden />
        <div className="flex-1">
          <h3 className="text-sm font-medium">
            {items.length === 1 ? "Last inbound message" : `Recent inbound (${data.count})`}
          </h3>
          {data.source ? (
            <p className="mt-0.5 text-xs text-fg-muted">source: {String(data.source)}</p>
          ) : null}
          {!data.found && items.length === 0 ? (
            <p className="mt-2 text-sm text-fg-muted">No inbound messages observed yet.</p>
          ) : (
            <ul className="mt-2 space-y-2">
              {items.map((m, i) => (
                <li key={i} className="rounded-card bg-bg-app p-2.5 text-sm">
                  <p className="font-medium">{m.sender}</p>
                  <p className="mt-1 whitespace-pre-wrap text-fg-muted">{m.text}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
