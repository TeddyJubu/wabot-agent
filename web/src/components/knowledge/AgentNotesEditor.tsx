import { useCallback, useEffect, useState } from "react";
import {
  deleteAgentNote,
  fetchAgentNotes,
  upsertAgentNote,
  type AgentNote,
} from "@/api/knowledge";

interface EditableNote {
  key: string;
  value: string;
  isNew?: boolean;
}

export default function AgentNotesEditor() {
  const [rows, setRows] = useState<EditableNote[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const data = await fetchAgentNotes();
    setRows(
      data.items.map((n: AgentNote) => ({
        key: n.key,
        value: n.value,
      })),
    );
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        await reload();
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load notes");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [reload]);

  async function saveRow(row: EditableNote, index: number) {
    if (!row.key.trim()) return;
    await upsertAgentNote(row.key.trim(), row.value);
    const next = [...rows];
    next[index] = { key: row.key.trim(), value: row.value };
    setRows(next);
  }

  async function removeRow(row: EditableNote, index: number) {
    if (!row.isNew && row.key) {
      await deleteAgentNote(row.key);
    }
    setRows(rows.filter((_, i) => i !== index));
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-fg-muted">
        Structured global notes stored in SQLite. Use the Memory tab for free-form operator
        knowledge in markdown.
      </p>
      {error && <p className="text-sm text-bad">{error}</p>}
      {loading && <p className="text-sm text-fg-muted">Loading…</p>}
      <div className="space-y-2">
        {rows.map((row, index) => (
          <div key={`${row.key}-${index}`} className="flex flex-wrap gap-2">
            <input
              aria-label="Note key"
              value={row.key}
              disabled={!row.isNew}
              onChange={(e) => {
                const next = [...rows];
                next[index] = { ...row, key: e.target.value };
                setRows(next);
              }}
              placeholder="key"
              className="min-w-[120px] flex-1 rounded-lg border border-border bg-bg-card px-3 py-2 font-mono text-sm"
            />
            <input
              aria-label="Note value"
              value={row.value}
              onChange={(e) => {
                const next = [...rows];
                next[index] = { ...row, value: e.target.value };
                setRows(next);
              }}
              placeholder="value"
              className="min-w-[160px] flex-[2] rounded-lg border border-border bg-bg-card px-3 py-2 text-sm"
            />
            <button
              type="button"
              className="rounded-pill border border-border px-3 py-2 text-sm hover:bg-bg-card"
              onClick={() => void saveRow(row, index)}
            >
              Save
            </button>
            <button
              type="button"
              className="rounded-pill px-3 py-2 text-sm text-bad hover:bg-bg-card"
              onClick={() => void removeRow(row, index)}
            >
              Delete
            </button>
          </div>
        ))}
      </div>
      <button
        type="button"
        className="rounded-pill border border-border px-4 py-2 text-sm hover:bg-bg-card"
        onClick={() => setRows([...rows, { key: "", value: "", isNew: true }])}
      >
        Add note
      </button>
    </div>
  );
}
