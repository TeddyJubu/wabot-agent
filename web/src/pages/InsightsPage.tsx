import {
  type KeyboardEvent,
  useEffect,
  useRef,
  useState,
} from "react";

import ActivityPanel from "@/components/slide-overs/ActivityPanel";
import OverviewPanel from "@/components/slide-overs/OverviewPanel";

type TabId = "live" | "log";

interface TabSpec {
  id: TabId;
  label: string;
}

const TABS: readonly TabSpec[] = [
  { id: "live", label: "Live" },
  { id: "log", label: "Log" },
];

const HASH_BY_TAB: Record<TabId, string> = {
  live: "#live",
  log: "#log",
};

function tabFromHash(hash: string): TabId {
  // Only `#log` flips to the Log tab; anything else (empty, `#live`, garbage)
  // falls back to Live. Keeping this strict so a typo doesn't strand the user
  // on a panel they didn't ask for.
  return hash === "#log" ? "log" : "live";
}

interface TabButtonProps {
  tab: TabSpec;
  isActive: boolean;
  onClick: () => void;
  buttonRef: (el: HTMLButtonElement | null) => void;
}

function TabButton({ tab, isActive, onClick, buttonRef }: TabButtonProps) {
  return (
    <button
      ref={buttonRef}
      type="button"
      role="tab"
      id={`insights-tab-${tab.id}`}
      aria-selected={isActive}
      aria-controls={`insights-panel-${tab.id}`}
      tabIndex={isActive ? 0 : -1}
      onClick={onClick}
      className={`px-4 py-3 min-h-[44px] text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
        isActive
          ? "border-b-2 border-accent text-accent"
          : "text-fg-muted hover:text-fg"
      }`}
    >
      {tab.label}
    </button>
  );
}

/**
 * Full-page Insights view shipped in Epic C2. Merges the legacy
 * OverviewPanel ("Live") and ActivityPanel ("Log") slide-overs behind a single
 * two-tab page. Only the active tab's panel is mounted so we don't double up
 * on the network calls each child fires on mount.
 *
 * The active tab is mirrored to the URL hash (`#live` / `#log`) via
 * history.replaceState — deep links and the back button stay coherent without
 * polluting the history stack.
 */
export default function InsightsPage() {
  const [activeTab, setActiveTab] = useState<TabId>(() =>
    typeof window === "undefined" ? "live" : tabFromHash(window.location.hash),
  );

  // Roving tab-index pattern — refs per-tab so ArrowLeft/ArrowRight can move
  // focus when the active tab changes.
  const tabRefs = useRef<Record<TabId, HTMLButtonElement | null>>({
    live: null,
    log: null,
  });
  // Only steal focus when the user navigated via keyboard. A plain mouse click
  // should keep focus wherever the user put it.
  const focusAfterChange = useRef(false);

  // Keep hash in sync on tab change. replaceState (not pushState) so back/forward
  // navigation isn't bloated with every tab toggle.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const desired = HASH_BY_TAB[activeTab];
    if (window.location.hash !== desired) {
      window.history.replaceState(null, "", desired);
    }
  }, [activeTab]);

  // Re-sync if the user navigates with the back button or edits the URL.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const handler = () => {
      setActiveTab(tabFromHash(window.location.hash));
    };
    window.addEventListener("popstate", handler);
    return () => window.removeEventListener("popstate", handler);
  }, []);

  useEffect(() => {
    if (!focusAfterChange.current) return;
    focusAfterChange.current = false;
    tabRefs.current[activeTab]?.focus();
  }, [activeTab]);

  const onTabKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const currentIdx = TABS.findIndex((t) => t.id === activeTab);
    if (currentIdx < 0) return;
    // ArrowLeft from the first tab wraps to the last; ArrowRight from the last
    // wraps to the first. Standard WAI-ARIA Authoring Practices roving
    // tablist pattern.
    const nextIdx =
      event.key === "ArrowRight"
        ? (currentIdx + 1) % TABS.length
        : (currentIdx - 1 + TABS.length) % TABS.length;
    const nextTab = TABS[nextIdx];
    if (!nextTab) return;
    focusAfterChange.current = true;
    setActiveTab(nextTab.id);
  };

  return (
    <div className="mx-auto w-full max-w-5xl">
      <h1 className="text-xl font-semibold text-fg mb-4">Insights</h1>
      <div
        role="tablist"
        aria-label="Insights sections"
        className="flex border-b border-border"
        onKeyDown={onTabKeyDown}
      >
        {TABS.map((tab) => (
          <TabButton
            key={tab.id}
            tab={tab}
            isActive={activeTab === tab.id}
            onClick={() => setActiveTab(tab.id)}
            buttonRef={(el) => {
              tabRefs.current[tab.id] = el;
            }}
          />
        ))}
      </div>

      {activeTab === "live" && (
        <div
          role="tabpanel"
          id="insights-panel-live"
          aria-labelledby="insights-tab-live"
          className="pt-6"
        >
          <OverviewPanel />
        </div>
      )}
      {activeTab === "log" && (
        <div
          role="tabpanel"
          id="insights-panel-log"
          aria-labelledby="insights-tab-log"
          className="pt-6"
        >
          <ActivityPanel />
        </div>
      )}
    </div>
  );
}
