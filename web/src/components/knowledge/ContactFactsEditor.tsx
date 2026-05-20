import { useCallback, useEffect, useState } from "react";
import {
  deleteContactFact,
  fetchContactFacts,
  fetchKnowledgeContacts,
  upsertContactFact,
  type ContactFact,
  type ContactSummary,
} from "@/api/knowledge";

interface EditableRow {
  key: string;
  value: string;
  isNew?: boolean;
}

export default function ContactFactsEditor() {
  const [contacts, setContacts] = useState<ContactSummary[]>([]);
  const [selected, setSelected] = useState("");
  const [rows, setRows] = useState<EditableRow[]>([]);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadContacts = useCallback(async () => {
    const data = await fetchKnowledgeContacts();
    setContacts(data.contacts);
    if (!selected && data.contacts.length > 0) {
      setSelected(data.contacts[0].contact);
    }
  }, [selected]);

  const loadFacts = useCallback(async (contact: string) => {
    if (!contact) {
      setRows([]);
      return;
    }
    const data = await fetchContactFacts(contact);
    setRows(
      data.facts.map((f: ContactFact) => ({
        key: f.key,
        value: f.value,
      })),
    );
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        await loadContacts();
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load contacts");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadContacts]);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    (async () => {
      try {
        await loadFacts(selected);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load facts");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selected, loadFacts]);

  const filteredContacts = contacts.filter((c) =>
    c.contact.toLowerCase().includes(filter.toLowerCase()),
  );

  async function saveRow(row: EditableRow, index: number) {
    if (!selected || !row.key.trim()) return;
    await upsertContactFact(selected, row.key.trim(), row.value);
    const next = [...rows];
    next[index] = { key: row.key.trim(), value: row.value };
    setRows(next);
    await loadContacts();
  }

  async function removeRow(row: EditableRow, index: number) {
    if (!selected) return;
    if (!row.isNew && row.key) {
      await deleteContactFact(selected, row.key);
      await loadContacts();
    }
    setRows(rows.filter((_, i) => i !== index));
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 lg:flex-row">
      <aside className="w-full shrink-0 space-y-2 lg:w-64">
        <label className="text-xs font-medium text-fg-muted">Search contacts</label>
        <input
          type="search"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="JID or name…"
          className="w-full rounded-lg border border-border bg-bg-card px-3 py-2 text-sm"
        />
        <ul className="max-h-64 overflow-auto rounded-lg border border-border lg:max-h-[480px]">
          {filteredContacts.map((c) => (
            <li key={c.contact}>
              <button
                type="button"
                onClick={() => setSelected(c.contact)}
                className={`w-full px-3 py-2 text-left text-sm transition hover:bg-bg-card ${
                  selected === c.contact ? "bg-bg-card font-medium" : ""
                }`}
              >
                <span className="block truncate">{c.contact}</span>
                <span className="text-xs text-fg-muted">{c.fact_count} facts</span>
              </button>
            </li>
          ))}
          {filteredContacts.length === 0 && !loading && (
            <li className="px-3 py-4 text-sm text-fg-muted">No contacts with facts yet.</li>
          )}
        </ul>
        <button
          type="button"
          className="w-full rounded-pill border border-dashed border-border px-3 py-2 text-sm text-fg-muted hover:border-accent hover:text-fg"
          onClick={() => {
            const jid = window.prompt("Contact JID (e.g. 15551234567@s.whatsapp.net)");
            if (jid?.trim()) {
              setSelected(jid.trim());
              setRows([]);
            }
          }}
        >
          Add contact…
        </button>
      </aside>
      <div className="min-h-0 flex-1 space-y-3">
        {error && <p className="text-sm text-bad">{error}</p>}
        {loading && <p className="text-sm text-fg-muted">Loading…</p>}
        {selected && (
          <>
            <p className="text-sm text-fg-muted">
              Editing facts for <span className="font-mono text-fg">{selected}</span>
            </p>
            <div className="space-y-2">
              {rows.map((row, index) => (
                <div key={`${row.key}-${index}`} className="flex flex-wrap gap-2">
                  <input
                    aria-label="Fact key"
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
                    aria-label="Fact value"
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
              data-testid="add-fact-row"
              className="rounded-pill border border-border px-4 py-2 text-sm hover:bg-bg-card"
              onClick={() => setRows([...rows, { key: "", value: "", isNew: true }])}
            >
              Add fact
            </button>
          </>
        )}
      </div>
    </div>
  );
}
