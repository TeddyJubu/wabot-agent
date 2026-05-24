import { useCallback, useEffect, useRef, useState } from "react";
import { BlockNoteView } from "@blocknote/mantine";
import { useCreateBlockNote } from "@blocknote/react";
import "@blocknote/mantine/style.css";

import { KnowledgeBudgetExceededError } from "@/api/knowledge";

interface BlockNoteEditorProps {
  label: string;
  initialMarkdown: string;
  maxChars: number;
  onSave: (markdown: string) => Promise<void>;
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

export default function BlockNoteEditor({
  label,
  initialMarkdown,
  maxChars,
  onSave,
  onDirtyChange,
}: BlockNoteEditorProps) {
  const editor = useCreateBlockNote();
  const [markdown, setMarkdown] = useState(initialMarkdown);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [budgetError, setBudgetError] = useState<BudgetError | null>(null);
  const loadedRef = useRef(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSavedRef = useRef(initialMarkdown);

  const charCount = markdown.length;
  const nearLimit = charCount > maxChars * 0.9;
  const overLimit = charCount > maxChars;

  const persist = useCallback(
    async (text: string) => {
      setSaving(true);
      setError(null);
      try {
        await onSave(text);
        lastSavedRef.current = text;
        setSavedAt(new Date().toLocaleTimeString());
        setBudgetError(null);
        onDirtyChange?.(false);
      } catch (err) {
        if (err instanceof KnowledgeBudgetExceededError) {
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
        setMarkdown(initialMarkdown);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [editor, initialMarkdown]);

  const scheduleSave = useCallback(
    (text: string) => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => {
        void persist(text);
      }, 2000);
    },
    [persist],
  );

  const handleChange = useCallback(async () => {
    if (!loadedRef.current) return;
    const text = await editor.blocksToMarkdownLossy(editor.document);
    setMarkdown(text);
    const dirty = text !== lastSavedRef.current;
    onDirtyChange?.(dirty);
    if (!dirty) return;
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
  }, [editor, onDirtyChange, scheduleSave, budgetError]);

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
          {savedAt && !saving && !budgetError && <span>Saved {savedAt}</span>}
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
      {budgetError && (
        <p className="text-sm text-bad" data-testid="budget-error">
          Content exceeds the {budgetError.budget.toLocaleString()}-character
          budget. Trim before it can save.
        </p>
      )}
      {error && !budgetError && <p className="text-sm text-bad">{error}</p>}
      <div className="min-h-[320px] flex-1 overflow-auto rounded-xl border border-border bg-bg-card p-2 [&_.bn-container]:min-h-[280px]">
        <BlockNoteView editor={editor} onChange={() => void handleChange()} />
      </div>
    </div>
  );
}
