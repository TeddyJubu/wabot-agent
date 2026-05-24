import {
  type KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { HelpPopover } from "@/components/HelpPopover";
import IntegrationsPanel from "@/components/slide-overs/IntegrationsPanel";
import ToolsPanel from "@/components/slide-overs/ToolsPanel";

type TabId = "sources" | "tools";

interface TabSpec {
  id: TabId;
  label: string;
}

const TABS: readonly TabSpec[] = [
  { id: "sources", label: "Sources" },
  { id: "tools", label: "Tools" },
];

/**
 * Parse the URL hash into a tab id + optional source-filter query. The hash
 * convention is `#tools?source=<name>` for the cross-link affordance and
 * plain `#sources` / `#tools` for direct deep links. Anything unrecognised
 * falls back to the Sources tab so a typo can't strand the user on an empty
 * panel.
 */
function parseHash(hash: string): { tab: TabId; source: string | null } {
  if (!hash) return { tab: "sources", source: null };
  const trimmed = hash.startsWith("#") ? hash.slice(1) : hash;
  const [base, query] = trimmed.split("?");
  let source: string | null = null;
  if (query) {
    const params = new URLSearchParams(query);
    source = params.get("source");
  }
  if (base === "tools") return { tab: "tools", source };
  return { tab: "sources", source: null };
}

function hashFor(tab: TabId, source: string | null): string {
  if (tab === "tools" && source) {
    const params = new URLSearchParams({ source });
    return `#tools?${params.toString()}`;
  }
  return `#${tab}`;
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
      id={`capabilities-tab-${tab.id}`}
      aria-selected={isActive}
      aria-controls={`capabilities-panel-${tab.id}`}
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
 * Full-page Capabilities view shipped in Epic C4. Merges the legacy
 * IntegrationsPanel ("Sources") and ToolsPanel ("Tools") slide-overs behind a
 * single two-tab page. Cross-link from a source to the Tools view is encoded
 * in the URL hash (`#tools?source=<name>`) — landing on Tools via that hash
 * shows a breadcrumb chip; clearing it strips the query.
 */
export default function CapabilitiesPage() {
  const initial = useMemo(
    () =>
      typeof window === "undefined"
        ? { tab: "sources" as TabId, source: null }
        : parseHash(window.location.hash),
    [],
  );
  const [activeTab, setActiveTab] = useState<TabId>(initial.tab);
  const [sourceFilter, setSourceFilter] = useState<string | null>(initial.source);

  // Roving tab-index pattern — refs per-tab so ArrowLeft/ArrowRight can move
  // focus when the active tab changes.
  const tabRefs = useRef<Record<TabId, HTMLButtonElement | null>>({
    sources: null,
    tools: null,
  });
  // Only steal focus when the user navigated via keyboard. A plain mouse click
  // should keep focus wherever the user put it.
  const focusAfterChange = useRef(false);

  // Keep hash in sync on tab/filter change. replaceState (not pushState) so
  // back/forward navigation isn't bloated with every tab toggle.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const desired = hashFor(activeTab, activeTab === "tools" ? sourceFilter : null);
    if (window.location.hash !== desired) {
      window.history.replaceState(null, "", desired);
    }
  }, [activeTab, sourceFilter]);

  // Re-sync if the user navigates with the back button or edits the URL.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const handler = () => {
      const parsed = parseHash(window.location.hash);
      setActiveTab(parsed.tab);
      setSourceFilter(parsed.source);
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

  const clearSourceFilter = useCallback(() => {
    setSourceFilter(null);
  }, []);

  return (
    <div className="mx-auto w-full max-w-5xl">
      <h1 className="text-xl font-semibold text-fg mb-4">Capabilities</h1>
      <div
        role="tablist"
        aria-label="Capabilities sections"
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

      {activeTab === "sources" && (
        <div
          role="tabpanel"
          id="capabilities-panel-sources"
          aria-labelledby="capabilities-tab-sources"
          className="pt-6"
        >
          <p className="mb-4 text-sm text-fg-muted">
            Sources install capabilities — like{" "}
            <HelpPopover term="MCP">
              Model Context Protocol — a server-to-LLM standard for exposing
              tools and data.
            </HelpPopover>{" "}
            servers and{" "}
            <HelpPopover term="Composio">
              Composio is a hosted directory of pre-built integrations (Slack,
              Notion, Drive, etc.) you can authorize and use via the agent.
            </HelpPopover>{" "}
            apps — that the agent then exposes as tools.
          </p>
          <IntegrationsPanel />
        </div>
      )}
      {activeTab === "tools" && (
        <div
          role="tabpanel"
          id="capabilities-panel-tools"
          aria-labelledby="capabilities-tab-tools"
          className="pt-6"
        >
          <p className="mb-4 text-sm text-fg-muted">
            Tools are the concrete callable functions the agent has access to —
            including{" "}
            <HelpPopover term="skill_action">
              A skill_action is a single callable function inside an installed
              skill (e.g. "search_emails" inside the gmail skill).
            </HelpPopover>
            .
          </p>
          {sourceFilter && (
            <div className="mb-4 flex items-center gap-2 rounded-pill border border-border bg-bg-card px-3 py-1.5 text-xs w-fit">
              <span className="text-fg-muted">
                Filtered by source: <span className="font-medium text-fg">{sourceFilter}</span>
              </span>
              <button
                type="button"
                onClick={clearSourceFilter}
                className="rounded-pill border border-border px-2 py-0.5 text-xs text-fg-muted transition hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                aria-label="Clear filter"
              >
                Clear filter
              </button>
            </div>
          )}
          <ToolsPanel />
        </div>
      )}
    </div>
  );
}
