import { useCallback, useEffect, useRef, useState } from "react";
import { BlockNoteView } from "@blocknote/mantine";
import { useCreateBlockNote } from "@blocknote/react";
import "@blocknote/mantine/style.css";

import {
  KnowledgeBudgetExceededError,
  KnowledgeStaleVersionError,
} from "@/api/knowledge";

interface BlockNoteEditorProps {
  label: string;
  initialMarkdown: string;
  /**
   * Version token corresponding to `initialMarkdown`. The editor passes
   * it as `If-Match` on every save so a concurrent edit elsewhere (CLI,
   * second tab) produces a 409 instead of silently clobbering.
   */
  initialVersion?: string;
  maxChars: number;
  /**
   * `ifMatch` is forwarded from the editor's loaded-version ref. The
   * implementation must pass it through to the network call. The return
   * value's `version` becomes the editor's new loaded-version baseline.
   */
  onSave: (markdown: string, ifMatch?: string) => Promise<{ version?: string } | void>;
  /**
   * Called when the operator clicks "Reload (lose my changes)" on the
   * conflict banner. The parent should overwrite its tracked content +
   * version so the editor re-mounts against the fresh server state.
   */
  onReloadFromServer?: (currentContent: string, currentVersion: string) => void;
  onDirtyChange?: (dirty: boolean) => void;
}

/**
 * Server-side budget error state. When set, the editor:
 *   - suppresses the client-side near/over warning text (the server has
 *     spoken; its message is more precise)
 *   - stops scheduling debounced retries for the same oversized content
 *   - keeps the document marked dirty so the navigation ConfirmDialog still
 *     fires
 * The next user edit that drops below `budget` clears this state and
 * autosave resumes on the normal debounce tick.
 */
interface BudgetError {
  budget: number;
  actual: number;
  /** Content length that produced the 413; used to gate retries. */
  rejectedLength: number;
}

/**
 * Optimistic-concurrency conflict state. When set, autosave is paused
 * and the editor renders a banner offering "Reload" or "Overwrite
 * anyway" — neither path silently merges. Mirrors the 413 budget-error
 * gating: dirty stays true, retries are paused.
 */
interface StaleConflict {
  currentContent: string;
  currentVersion: string;
}

export default function BlockNoteEditor({
  label,
  initialMarkdown,
  initialVersion,
  maxChars,
  onSave,
  onReloadFromServer,
  onDirtyChange,
}: BlockNoteEditorProps) {
  const editor = useCreateBlockNote();
  const [markdown, setMarkdown] = useState(initialMarkdown);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [budgetError, setBudgetError] = useState<BudgetError | null>(null);
  const [staleConflict, setStaleConflict] = useState<StaleConflict | null>(null);
  const loadedRef = useRef(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSavedRef = useRef(initialMarkdown);
  // Version token of whatever's currently loaded into the editor.
  // Sent as `If-Match` on every save; updated on successful save (with
  // the version returned by the server) and on initial load.
  const loadedVersionRef = useRef<string | undefined>(initialVersion);

  const charCount = markdown.length;
  const nearLimit = charCount > maxChars * 0.9;
  const overLimit = charCount > maxChars;

  const persist = useCallback(
    async (text: string, overrideIfMatch?: string) => {
      setSaving(true);
      setError(null);
      const ifMatch = overrideIfMatch ?? loadedVersionRef.current;
      try {
        const result = await onSave(text, ifMatch);
        lastSavedRef.current = text;
        // Adopt the server's new version as the editor's baseline so the
        // next save's If-Match is fresh. If the parent did not return a
        // meta object (older signature), fall back to clearing the ref.
        if (result && typeof result === "object" && typeof result.version === "string") {
          loadedVersionRef.current = result.version;
        }
        setSavedAt(new Date().toLocaleTimeString());
        setBudgetError(null);
        setStaleConflict(null);
        onDirtyChange?.(false);
      } catch (err) {
        if (err instanceof KnowledgeStaleVersionError) {
          // 409 takes precedence over a pending 413 — losing data is
          // worse than rejecting an over-budget save. Stop autosave,
          // render the conflict banner, keep dirty flag set.
          setStaleConflict({
            currentContent: err.currentContent,
            currentVersion: err.currentVersion,
          });
          setBudgetError(null);
          onDirtyChange?.(true);
        } else if (err instanceof KnowledgeBudgetExceededError) {
          // Server rejected with 413. Record the length so the debounce
          // schedule can refuse to re-fire until the user edits below budget.
          setBudgetError({
            budget: err.budget,
            actual: err.actual,
            rejectedLength: text.length,
          });
          // Keep the document marked dirty so the navigation ConfirmDialog
          // still fires — `lastSavedRef` is intentionally NOT updated.
          onDirtyChange?.(true);
        } else {
          setError(err instanceof Error ? err.message : "Save failed");
        }
      } finally {
        setSaving(false);
      }
    },
    [onSave, onDirtyChange],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const blocks = await editor.tryParseMarkdownToBlocks(initialMarkdown || "");
      if (!cancelled) {
        editor.replaceBlocks(editor.document, blocks);
        loadedRef.current = true;
        lastSavedRef.current = initialMarkdown;
        // Reset the version baseline whenever the parent swaps in fresh
        // content (initial mount, post-reload after conflict).
        loadedVersionRef.current = initialVersion;
        setMarkdown(initialMarkdown);
        // A fresh load implicitly resolves any prior conflict — the
        // editor is now showing whatever the parent passed in.
        setStaleConflict(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [editor, initialMarkdown, initialVersion]);

  const scheduleSave = useCallback(
    (text: string) => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => {
        void persist(text);
      }, 2000);
    },
    [persist],
  );

  // Cancel any pending autosave when the editor unmounts (tab switch,
  // navigation, parent re-render that swaps key). Without this the
  // debounced timer fires against a stale closure and either no-ops or
  // throws on a unmounted component during the fetch.
  useEffect(() => {
    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
        debounceRef.current = null;
      }
    };
  }, []);

  const handleChange = useCallback(async () => {
    if (!loadedRef.current) return;
    const text = await editor.blocksToMarkdownLossy(editor.document);
    setMarkdown(text);
    const dirty = text !== lastSavedRef.current;
    onDirtyChange?.(dirty);
    if (!dirty) return;
    // Conflict banner pending — never autosave behind the operator's
    // back. They must explicitly Reload or Overwrite anyway first.
    if (staleConflict) return;
    // If the server has already rejected this content as too large, refuse to
    // schedule another autosave until the user trims it. Comparing on length
    // is good enough: same length almost certainly means same payload, and a
    // truly-different same-length edit will fail the same way one tick later.
    // Once the user drops below the rejected size, clear the error and let
    // the debounce resume on the next change.
    if (budgetError) {
      if (text.length < budgetError.rejectedLength) {
        setBudgetError(null);
        scheduleSave(text);
      }
      // else: stuck at or above rejected size — do not hammer the server.
      return;
    }
    scheduleSave(text);
  }, [editor, onDirtyChange, scheduleSave, budgetError, staleConflict]);

  const handleReloadFromServer = useCallback(() => {
    if (!staleConflict) return;
    onReloadFromServer?.(staleConflict.currentContent, staleConflict.currentVersion);
    // The parent will re-render with fresh initialMarkdown/initialVersion,
    // which fires the load useEffect and resets the conflict + version
    // baseline. Clear locally too in case the parent does not echo back.
    setStaleConflict(null);
  }, [onReloadFromServer, staleConflict]);

  const handleOverwriteAnyway = useCallback(() => {
    if (!staleConflict) return;
    // Re-issue the save with If-Match = the server's current_version so
    // the next request succeeds (assuming no further concurrent write).
    void persist(markdown, staleConflict.currentVersion);
  }, [persist, markdown, staleConflict]);

  // Server-side budget error wins over client-side near/over warning — the
  // server has spoken, its message is precise, and the counter should reflect
  // the budget the server enforces (not the client's `maxChars` prop if they
  // ever drift). When the budget error is present, the counter shows red.
  const counterClass = budgetError
    ? "text-bad"
    : overLimit
    ? "text-bad"
    : nearLimit
    ? "text-warn"
    : undefined;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-medium text-fg">{label}</h2>
        <div className="flex items-center gap-3 text-xs text-fg-muted">
          <span className={counterClass} data-testid="char-counter">
            {charCount.toLocaleString()} /{" "}
            {(budgetError?.budget ?? maxChars).toLocaleString()} chars
          </span>
          {saving && <span>Saving…</span>}
          {savedAt && !saving && !budgetError && !staleConflict && (
            <span>Saved {savedAt}</span>
          )}
          <button
            type="button"
            className="rounded-pill border border-border px-3 py-1 text-fg transition hover:bg-bg-card disabled:opacity-50"
            disabled={saving || markdown === lastSavedRef.current}
            onClick={() => void persist(markdown)}
          >
            Save now
          </button>
        </div>
      </div>
      {/* 409 conflict wins over 413 — losing the operator's edits is worse
          than rejecting an over-budget save, so the banner UI prioritises
          the conflict-resolution flow. */}
      {staleConflict ? (
        <div
          className="flex flex-col gap-2 rounded-xl border border-bad bg-bg-card p-3"
          data-testid="stale-conflict-banner"
          role="alert"
        >
          <p className="text-sm text-bad">
            This document was modified elsewhere.
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="rounded-pill border border-border px-3 py-1 text-sm text-fg transition hover:bg-bg-app"
              onClick={handleReloadFromServer}
              data-testid="stale-conflict-reload"
            >
              Reload (lose my changes)
            </button>
            <button
              type="button"
              className="rounded-pill border border-border px-3 py-1 text-sm text-fg transition hover:bg-bg-app"
              onClick={handleOverwriteAnyway}
              data-testid="stale-conflict-overwrite"
            >
              Overwrite anyway
            </button>
          </div>
        </div>
      ) : budgetError ? (
        <p className="text-sm text-bad" data-testid="budget-error">
          Content exceeds the {budgetError.budget.toLocaleString()}-character
          budget. Trim before it can save.
        </p>
      ) : null}
      {error && !budgetError && !staleConflict && (
        <p className="text-sm text-bad">{error}</p>
      )}
      <div className="min-h-[320px] flex-1 overflow-auto rounded-xl border border-border bg-bg-card p-2 [&_.bn-container]:min-h-[280px]">
        <BlockNoteView editor={editor} onChange={() => void handleChange()} />
      </div>
    </div>
  );
}
