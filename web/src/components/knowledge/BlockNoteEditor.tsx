import { useCallback, useEffect, useRef, useState } from "react";
import { BlockNoteView } from "@blocknote/mantine";
import { useCreateBlockNote } from "@blocknote/react";
import "@blocknote/mantine/style.css";

interface BlockNoteEditorProps {
  label: string;
  initialMarkdown: string;
  maxChars: number;
  onSave: (markdown: string) => Promise<void>;
  onDirtyChange?: (dirty: boolean) => void;
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
  const loadedRef = useRef(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const markdownDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
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
        onDirtyChange?.(false);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Save failed");
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

  const handleChange = useCallback(() => {
    if (!loadedRef.current) return;
    if (markdownDebounceRef.current) clearTimeout(markdownDebounceRef.current);
    markdownDebounceRef.current = setTimeout(() => {
      void (async () => {
        const text = await editor.blocksToMarkdownLossy(editor.document);
        setMarkdown(text);
        const dirty = text !== lastSavedRef.current;
        onDirtyChange?.(dirty);
        if (dirty) scheduleSave(text);
      })();
    }, 300);
  }, [editor, onDirtyChange, scheduleSave]);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-medium text-fg">{label}</h2>
        <div className="flex items-center gap-3 text-xs text-fg-muted">
          <span
            className={overLimit ? "text-bad" : nearLimit ? "text-warn" : undefined}
            data-testid="char-counter"
          >
            {charCount.toLocaleString()} / {maxChars.toLocaleString()} chars
          </span>
          {saving && <span>Saving…</span>}
          {savedAt && !saving && <span>Saved {savedAt}</span>}
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
      {error && <p className="text-sm text-bad">{error}</p>}
      <div className="min-h-[320px] flex-1 overflow-auto rounded-xl border border-border bg-bg-card p-2 [&_.bn-container]:min-h-[280px]">
        <BlockNoteView editor={editor} onChange={() => void handleChange()} />
      </div>
    </div>
  );
}
