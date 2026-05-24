import { useState } from "react";
import clsx from "clsx";
import { RunsTab } from "./activity/RunsTab";
import { InboxTab } from "./activity/InboxTab";
import { ToolEventsTab } from "./activity/ToolEventsTab";
import { CostsTab } from "./activity/CostsTab";

type TabId = "runs" | "inbox" | "tool_events" | "costs";

const TABS: { id: TabId; label: string }[] = [
  { id: "runs", label: "Runs" },
  { id: "inbox", label: "Inbox" },
  { id: "tool_events", label: "Tool events" },
  { id: "costs", label: "Costs" },
];

export default function ActivityPanel() {
  const [tab, setTab] = useState<TabId>("runs");

  return (
    <div>
      {/* Tab bar */}
      <div className="mb-4 flex gap-0.5 border-b border-border">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={clsx(
              "px-3 py-1.5 text-xs font-medium transition",
              tab === t.id
                ? "border-b-2 border-accent text-fg -mb-px"
                : "text-fg-muted hover:text-fg",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === "runs" && <RunsTab />}
      {tab === "inbox" && <InboxTab />}
      {tab === "tool_events" && <ToolEventsTab />}
      {tab === "costs" && <CostsTab />}
    </div>
  );
}
