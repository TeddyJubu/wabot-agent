import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, BookOpen } from "lucide-react";
import {
  fetchInstructions,
  fetchKnowledgeIndex,
  fetchMemory,
  saveInstructions,
  saveMemory,
} from "@/api/knowledge";
import AgentNotesEditor from "@/components/knowledge/AgentNotesEditor";
import BlockNoteEditor from "@/components/knowledge/BlockNoteEditor";
import ContactFactsEditor from "@/components/knowledge/ContactFactsEditor";

type TabId = "instructions" | "memory" | "contacts" | "notes";

const TABS: { id: TabId; label: string }[] = [
  { id: "instructions", label: "Instructions" },
  { id: "memory", label: "Memory" },
  { id: "contacts", label: "Contacts" },
  { id: "notes", label: "Notes" },
];

export default function KnowledgePage() {
  const [tab, setTab] = useState<TabId>("instructions");
  const [budgets, setBudgets] = useState({ instructions: 6000, memory: 4000, contact: 2000 });
  const [instructions, setInstructions] = useState("");
  const [memory, setMemory] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const index = await fetchKnowledgeIndex();
      setBudgets(index.budgets);
      const [ins, mem] = await Promise.all([fetchInstructions(), fetchMemory()]);
      setInstructions(ins.content);
      setMemory(mem.content);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load knowledge");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (!dirty) return;
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  function navigateHome() {
    if (dirty && !window.confirm("You have unsaved changes. Leave anyway?")) return;
    window.location.href = "/";
  }

  function switchTab(next: TabId) {
    if (dirty && !window.confirm("You have unsaved changes. Switch tabs anyway?")) return;
    setTab(next);
    setDirty(false);
  }

  return (
    <div className="flex h-full min-h-screen flex-col bg-bg-app text-fg">
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-border px-4">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={navigateHome}
            className="inline-flex items-center gap-1 text-sm text-fg-muted transition hover:text-fg"
            aria-label="Back to chat"
          >
            <ArrowLeft className="size-4" />
            Chat
          </button>
          <span className="inline-flex items-center gap-2 font-medium">
            <BookOpen className="size-4 text-accent" />
            Knowledge
          </span>
        </div>
      </header>
      <nav
        className="flex shrink-0 gap-1 border-b border-border px-4"
        aria-label="Knowledge sections"
      >
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => switchTab(t.id)}
            className={`border-b-2 px-4 py-2 text-sm transition ${
              tab === t.id
                ? "border-accent text-fg"
                : "border-transparent text-fg-muted hover:text-fg"
            }`}
          >
            {t.label}
          </button>
        ))}
      </nav>
      <main className="flex min-h-0 flex-1 flex-col p-4">
        {error && <p className="mb-2 text-sm text-bad">{error}</p>}
        {loading && tab !== "contacts" && tab !== "notes" && (
          <p className="text-sm text-fg-muted">Loading…</p>
        )}
        {tab === "instructions" && !loading && (
          <BlockNoteEditor
            label="Client instructions"
            initialMarkdown={instructions}
            maxChars={budgets.instructions}
            onSave={async (content) => {
              await saveInstructions(content);
              setInstructions(content);
            }}
            onDirtyChange={setDirty}
          />
        )}
        {tab === "memory" && !loading && (
          <BlockNoteEditor
            label="Operator memory"
            initialMarkdown={memory}
            maxChars={budgets.memory}
            onSave={async (content) => {
              await saveMemory(content);
              setMemory(content);
            }}
            onDirtyChange={setDirty}
          />
        )}
        {tab === "contacts" && <ContactFactsEditor />}
        {tab === "notes" && <AgentNotesEditor />}
      </main>
    </div>
  );
}
