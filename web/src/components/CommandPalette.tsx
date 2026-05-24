import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { SLASH_COMMANDS } from "@/hooks/useSlashCommands";
import {
  getSearchIndex,
  rankResults,
  type SearchResult,
  type SearchResultKind,
} from "@/searchIndex";

export interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  /** Called with the sentinel string from a SlashCommand's `expand()`. */
  onDispatch: (sentinel: string) => void;
}

const MAX_RESULTS = 50;

const GROUP_ORDER: readonly SearchResultKind[] = [
  "command",
  "knowledge",
  "agent",
  "tool",
  "settings",
];

const GROUP_LABEL: Record<SearchResultKind, string> = {
  command: "Commands",
  knowledge: "Knowledge",
  agent: "Agents",
  tool: "Tools",
  settings: "Settings",
};

/** Fallback index built synchronously from SLASH_COMMANDS so the palette can
 * render something useful before `getSearchIndex()` resolves. */
function buildSyncCommandFallback(): SearchResult[] {
  return SLASH_COMMANDS.map((c) => ({
    kind: "command" as const,
    id: c.name,
    label: c.name,
    description: c.description,
    sentinel: c.expand(),
  }));
}

/**
 * Group a flat ranked list by kind, preserving the input order inside each
 * group. Returns the groups in `GROUP_ORDER`, skipping empty ones.
 */
function groupByKind(
  results: SearchResult[],
): { kind: SearchResultKind; items: SearchResult[] }[] {
  const buckets = new Map<SearchResultKind, SearchResult[]>();
  for (const r of results) {
    const arr = buckets.get(r.kind);
    if (arr) arr.push(r);
    else buckets.set(r.kind, [r]);
  }
  return GROUP_ORDER.filter((k) => buckets.has(k)).map((k) => ({
    kind: k,
    items: buckets.get(k) ?? [],
  }));
}

/**
 * Global Cmd-K / Ctrl-K / `/` command palette. Backed by `getSearchIndex()` —
 * a lazy in-memory index built once per session covering commands, knowledge
 * docs, agents, tools and well-known settings keys.
 */
export default function CommandPalette({
  open,
  onClose,
  onDispatch,
}: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [activeIdx, setActiveIdx] = useState(0);
  const [index, setIndex] = useState<SearchResult[] | null>(null);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  // Kick off the lazy search-index build whenever the palette opens. Cached
  // by `getSearchIndex`, so reopening is essentially free.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    getSearchIndex()
      .then((items) => {
        if (cancelled) return;
        setIndex(items);
      })
      .catch(() => {
        if (cancelled) return;
        // Degrade gracefully — fall back to the command-only sync index.
        setIndex(buildSyncCommandFallback());
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  // The effective index: real one if loaded, sync command fallback otherwise.
  const effectiveIndex = useMemo<SearchResult[]>(
    () => index ?? buildSyncCommandFallback(),
    [index],
  );

  const ranked = useMemo<SearchResult[]>(() => {
    const all = rankResults(query, effectiveIndex);
    return all.slice(0, MAX_RESULTS);
  }, [query, effectiveIndex]);

  const groups = useMemo(() => groupByKind(ranked), [ranked]);

  // Flat list in render order — used for keyboard navigation and Enter
  // dispatch. Must match the order rows appear in the DOM.
  const flat = useMemo<SearchResult[]>(
    () => groups.flatMap((g) => g.items),
    [groups],
  );

  // Reset internal state whenever the palette closes — so the next open is a
  // clean slate.
  useEffect(() => {
    if (!open) {
      setQuery("");
      setActiveIdx(0);
    }
  }, [open]);

  // Keep activeIdx in range whenever the visible list shrinks.
  useEffect(() => {
    if (activeIdx > flat.length - 1) {
      setActiveIdx(flat.length === 0 ? 0 : flat.length - 1);
    }
  }, [flat.length, activeIdx]);

  // Focus management — capture the previously focused element on open and
  // restore it on close. Mirrors the ConfirmDialog pattern.
  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    inputRef.current?.focus();
    return () => {
      previouslyFocused?.focus?.();
    };
  }, [open]);

  if (!open) return null;

  function handleKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, Math.max(flat.length - 1, 0)));
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const picked = flat[activeIdx];
      if (picked) {
        onDispatch(picked.sentinel);
        onClose();
      }
    }
  }

  const activeId = flat.length > 0 ? `cmdp-item-${activeIdx}` : undefined;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 p-4 pt-24"
      onKeyDown={handleKeyDown}
    >
      <div
        data-testid="cmdp-backdrop"
        className="absolute inset-0"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        className="relative w-full max-w-[520px] overflow-hidden rounded-card border border-border bg-bg-card text-fg shadow-xl"
      >
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setActiveIdx(0);
          }}
          role="combobox"
          aria-expanded="true"
          aria-controls="cmdp-listbox"
          aria-activedescendant={activeId}
          aria-label="Command"
          placeholder="Type a command…"
          className="block w-full border-b border-border bg-transparent px-4 py-3 text-sm placeholder:text-fg-muted focus:outline-none"
        />
        <div
          id="cmdp-listbox"
          role="listbox"
          aria-label="Commands"
          className="max-h-80 overflow-y-auto py-1"
        >
          {loading && index === null ? (
            <div
              className="px-4 py-2 text-xs text-fg-muted"
              data-testid="cmdp-loading"
            >
              Loading…
            </div>
          ) : null}
          {flat.length === 0 ? (
            <div
              role="option"
              aria-selected="false"
              className="px-4 py-3 text-sm text-fg-muted"
            >
              No commands match.
            </div>
          ) : (
            (() => {
              // Walk a running offset so each row's id matches its position
              // in `flat`. Keeping this inline avoids a stateful effect.
              let offset = 0;
              return groups.map((group) => {
                const start = offset;
                offset += group.items.length;
                return (
                <div
                  key={`group-${group.kind}`}
                  role="group"
                  aria-label={GROUP_LABEL[group.kind]}
                  className="py-1"
                >
                  <div
                    role="presentation"
                    className="px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-fg-muted"
                  >
                    {GROUP_LABEL[group.kind]}
                  </div>
                  {group.items.map((r, i) => {
                    const flatIdx = start + i;
                    const active = flatIdx === activeIdx;
                    return (
                      <div
                        key={`${r.kind}-${r.id}`}
                        id={`cmdp-item-${flatIdx}`}
                        role="option"
                        aria-selected={active}
                        onMouseEnter={() => setActiveIdx(flatIdx)}
                        onClick={() => {
                          onDispatch(r.sentinel);
                          onClose();
                        }}
                        className={`flex cursor-pointer items-center justify-between gap-3 px-4 py-2 text-sm transition ${
                          active ? "bg-accent/10 text-accent" : "text-fg"
                        }`}
                      >
                        <span className="flex min-w-0 items-center gap-3">
                          <span className="font-mono">{r.label}</span>
                          {r.description ? (
                            <span className="truncate text-xs text-fg-muted">
                              {r.description}
                            </span>
                          ) : null}
                        </span>
                        <span className="rounded-pill border border-border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide text-fg-muted">
                          {GROUP_LABEL[r.kind]}
                        </span>
                      </div>
                    );
                  })}
                </div>
                );
              });
            })()
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
