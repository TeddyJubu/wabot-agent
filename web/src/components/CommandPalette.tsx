import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { SLASH_COMMANDS, type SlashCommand } from "@/hooks/useSlashCommands";

export interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  /** Called with the sentinel string from a SlashCommand's `expand()`. */
  onDispatch: (sentinel: string) => void;
}

/**
 * Global Cmd-K / Ctrl-K / `/` command palette. Mirrors the same command set
 * surfaced by the legacy bottom slash menu (`SLASH_COMMANDS`), but with a more
 * forgiving substring matcher over both name and description.
 *
 * Owners pass `open`, `onClose`, and `onDispatch`. The palette never reads from
 * the URL or any store — App owns the keybinding wiring and the dispatch
 * sentinel handling.
 */
export default function CommandPalette({
  open,
  onClose,
  onDispatch,
}: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [activeIdx, setActiveIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const matches = useMemo<SlashCommand[]>(() => {
    const q = query.trim().toLowerCase();
    if (!q) return SLASH_COMMANDS;
    return SLASH_COMMANDS.filter(
      (c) =>
        c.name.toLowerCase().includes(q) ||
        c.description.toLowerCase().includes(q),
    );
  }, [query]);

  // Reset internal state whenever the palette closes — so the next open is a
  // clean slate.
  useEffect(() => {
    if (!open) {
      setQuery("");
      setActiveIdx(0);
    }
  }, [open]);

  // Keep activeIdx in range whenever the match list shrinks.
  useEffect(() => {
    if (activeIdx > matches.length - 1) {
      setActiveIdx(matches.length === 0 ? 0 : matches.length - 1);
    }
  }, [matches.length, activeIdx]);

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
      setActiveIdx((i) => Math.min(i + 1, Math.max(matches.length - 1, 0)));
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const cmd = matches[activeIdx];
      if (cmd) {
        onDispatch(cmd.expand());
        onClose();
      }
    }
  }

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
          aria-activedescendant={
            matches.length > 0 ? `cmdp-item-${activeIdx}` : undefined
          }
          aria-label="Command"
          placeholder="Type a command…"
          className="block w-full border-b border-border bg-transparent px-4 py-3 text-sm placeholder:text-fg-muted focus:outline-none"
        />
        <ul
          id="cmdp-listbox"
          role="listbox"
          aria-label="Commands"
          className="max-h-80 overflow-y-auto py-1"
        >
          {matches.length === 0 ? (
            <li
              role="option"
              aria-selected="false"
              className="px-4 py-3 text-sm text-fg-muted"
            >
              No commands match.
            </li>
          ) : (
            matches.map((c, i) => {
              const active = i === activeIdx;
              return (
                <li
                  key={c.name}
                  id={`cmdp-item-${i}`}
                  role="option"
                  aria-selected={active}
                  onMouseEnter={() => setActiveIdx(i)}
                  onClick={() => {
                    onDispatch(c.expand());
                    onClose();
                  }}
                  className={`flex cursor-pointer items-center justify-between gap-3 px-4 py-2 text-sm transition ${
                    active ? "bg-accent/10 text-accent" : "text-fg"
                  }`}
                >
                  <span className="flex min-w-0 items-center gap-3">
                    <span className="font-mono">{c.name}</span>
                    <span className="truncate text-xs text-fg-muted">
                      {c.description}
                    </span>
                  </span>
                  {c.shortcut ? (
                    <span className="rounded-pill border border-border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide text-fg-muted">
                      {c.shortcut}
                    </span>
                  ) : null}
                </li>
              );
            })
          )}
        </ul>
      </div>
    </div>,
    document.body,
  );
}
