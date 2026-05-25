import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, BookOpen } from "lucide-react";
import {
  fetchInstructions,
  fetchKnowledgeIndex,
  saveInstructions,
} from "@/api/knowledge";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import AgentNotesEditor from "@/components/knowledge/AgentNotesEditor";
import BlockNoteEditor from "@/components/knowledge/BlockNoteEditor";
import ContactFactsEditor from "@/components/knowledge/ContactFactsEditor";

type TabId = "instructions" | "contacts" | "notes";

const TABS: { id: TabId; label: string }[] = [
  { id: "instructions", label: "Instructions" },
  { id: "contacts", label: "Contacts" },
  { id: "notes", label: "Notes" },
];

// Phase 2a: a single 10000-char instructions budget replaced the old split
// (6000 instructions + 4000 memory). The number here is only a fallback for
// the brief window before /api/knowledge resolves — the live budget always
// wins via setBudgets() below.
const DEFAULT_BUDGETS = { instructions: 10000, contact: 2000 };

export default function KnowledgePage() {
  const [tab, setTab] = useState<TabId>("instructions");
  const [budgets, setBudgets] = useState(DEFAULT_BUDGETS);
  const [instructions, setInstructions] = useState("");
  // Version token paired with `instructions`. Passed to BlockNoteEditor as
  // `initialVersion` and sent back to the server as `If-Match` on save.
  const [instructionsVersion, setInstructionsVersion] = useState<string | undefined>(
    undefined,
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [pendingTab, setPendingTab] = useState<TabId | null>(null);
  const [confirmLeaveOpen, setConfirmLeaveOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const index = await fetchKnowledgeIndex();
      setBudgets(index.budgets);
      const ins = await fetchInstructions();
      setInstructions(ins.content);
      setInstructionsVersion(ins.version);
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
    if (dirty) {
      setConfirmLeaveOpen(true);
      return;
    }
    window.location.href = "/";
  }

  function switchTab(next: TabId) {
    if (next === tab) return;
    if (dirty) {
      setPendingTab(next);
      return;
    }
    setTab(next);
    setDirty(false);
  }

  function confirmSwitchTab() {
    if (!pendingTab) return;
    setTab(pendingTab);
    setPendingTab(null);
    setDirty(false);
  }

  function confirmLeave() {
    setConfirmLeaveOpen(false);
    window.location.href = "/";
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
            initialVersion={instructionsVersion}
            maxChars={budgets.instructions}
            onSave={async (content, ifMatch) => {
              const meta = await saveInstructions(content, ifMatch);
              setInstructions(content);
              setInstructionsVersion(meta.version);
              return { version: meta.version };
            }}
            onReloadFromServer={(currentContent, currentVersion) => {
              // Adopt the server's view: editor re-mounts (initialMarkdown
              // changed), conflict clears, version baseline resets.
              setInstructions(currentContent);
              setInstructionsVersion(currentVersion);
            }}
            onDirtyChange={setDirty}
          />
        )}
        {tab === "contacts" && <ContactFactsEditor />}
        {tab === "notes" && <AgentNotesEditor />}
      </main>

      <ConfirmDialog
        open={confirmLeaveOpen}
        title="Discard unsaved changes?"
        description="Leaving will lose your edits."
        confirmLabel="Discard and leave"
        variant="danger"
        onConfirm={confirmLeave}
        onCancel={() => setConfirmLeaveOpen(false)}
      />

      <ConfirmDialog
        open={pendingTab !== null}
        title="Discard unsaved changes?"
        description="Switching tabs will lose your edits."
        confirmLabel="Discard and switch"
        variant="danger"
        onConfirm={confirmSwitchTab}
        onCancel={() => setPendingTab(null)}
      />
    </div>
  );
}
